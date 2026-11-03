"""Local accounts: scrypt hashing, roles, lockout and audit."""

from __future__ import annotations

import pytest

from retvia.core.errors import BusinessRuleError, DuplicateError, NotFoundError, ValidationError
from retvia.services.users import (
    MAX_FAILED_ATTEMPTS,
    PERMISSIONS,
    UserService,
    hash_password,
    verify_password,
)


@pytest.fixture
def users(db, audit):
    return UserService(db, audit)


class TestHashing:
    def test_hash_is_not_the_password(self):
        digest, salt = hash_password("secret123")
        assert digest != "secret123"
        assert len(bytes.fromhex(digest)) == 32
        assert len(bytes.fromhex(salt)) == 16

    def test_same_password_different_salt(self):
        first, salt1 = hash_password("secret123")
        second, salt2 = hash_password("secret123")
        assert salt1 != salt2
        assert first != second

    def test_verify_accepts_correct_password(self):
        digest, salt = hash_password("secret123")
        assert verify_password("secret123", digest, salt) is True

    def test_verify_rejects_wrong_password(self):
        digest, salt = hash_password("secret123")
        assert verify_password("secret124", digest, salt) is False

    def test_verify_is_timing_safe_against_garbage(self):
        assert verify_password("x", "not-hex", "not-hex") is False

    def test_short_password_rejected(self):
        with pytest.raises(ValidationError):
            hash_password("short")

    def test_unicode_password_supported(self):
        digest, salt = hash_password("পাসওয়ার্ড১২৩")
        assert verify_password("পাসওয়ার্ড১২৩", digest, salt)


class TestAccounts:
    def test_create_and_list(self, users):
        user_id = users.create(username="Admin", password="password1", display_name="মালিক", role="owner")
        assert user_id > 0
        rows = users.list()
        assert rows[0]["username"] == "admin", "usernames are case-folded"
        assert "password_hash" not in rows[0], "hashes must never leave the service"

    def test_duplicate_username_rejected(self, users):
        users.create(username="admin", password="password1", display_name="এক")
        with pytest.raises(DuplicateError):
            users.create(username="ADMIN", password="password1", display_name="দুই")

    def test_username_with_space_rejected(self, users):
        with pytest.raises(ValidationError):
            users.create(username="two words", password="password1", display_name="নাম")

    def test_invalid_role_rejected(self, users):
        with pytest.raises(ValidationError):
            users.create(username="x", password="password1", display_name="নাম", role="superuser")

    def test_get_missing_raises(self, users):
        with pytest.raises(NotFoundError):
            users.get(999)

    def test_ensure_owner_only_once(self, users):
        first = users.ensure_owner(username="admin", password="password1", display_name="মালিক")
        assert first is not None
        assert users.ensure_owner(username="other", password="password1", display_name="অন্য") is None
        assert users.count() == 1

    def test_audit_recorded(self, users, db):
        users.create(username="admin", password="password1", display_name="মালিক")
        rows = db.query("SELECT action FROM audit_logs WHERE entity_type='user'")
        assert "create" in [r["action"] for r in rows]


class TestAuthentication:
    def test_successful_login(self, users):
        users.create(username="admin", password="password1", display_name="মালিক", role="owner")
        user = users.authenticate("admin", "password1")
        assert user["role"] == "owner"
        assert users.get(user["id"])["last_login_at"] != ""

    def test_login_is_case_insensitive_on_username(self, users):
        users.create(username="admin", password="password1", display_name="মালিক")
        assert users.authenticate("ADMIN", "password1")["username"] == "admin"

    def test_wrong_password_rejected(self, users):
        users.create(username="admin", password="password1", display_name="মালিক")
        with pytest.raises(BusinessRuleError):
            users.authenticate("admin", "wrongpass")

    def test_unknown_user_message_is_generic(self, users):
        with pytest.raises(BusinessRuleError) as info:
            users.authenticate("ghost", "whatever")
        assert "সঠিক নয়" in str(info.value)

    def test_inactive_account_rejected(self, users):
        users.create(username="owner", password="password1", display_name="মালিক", role="owner")
        user_id = users.create(username="cashier", password="password1", display_name="ক্যাশিয়ার")
        users.set_active(user_id, False)
        with pytest.raises(BusinessRuleError):
            users.authenticate("cashier", "password1")

    def test_lockout_after_repeated_failures(self, users):
        users.create(username="admin", password="password1", display_name="মালিক")
        for _ in range(MAX_FAILED_ATTEMPTS):
            with pytest.raises(BusinessRuleError):
                users.authenticate("admin", "bad")
        with pytest.raises(BusinessRuleError) as info:
            users.authenticate("admin", "password1")
        assert "সাময়িকভাবে বন্ধ" in str(info.value)

    def test_password_reset_clears_lockout(self, users):
        user_id = users.create(username="admin", password="password1", display_name="মালিক")
        for _ in range(MAX_FAILED_ATTEMPTS):
            with pytest.raises(BusinessRuleError):
                users.authenticate("admin", "bad")
        users.set_password(user_id, "newpassword")
        assert users.authenticate("admin", "newpassword")["id"] == user_id

    def test_login_attempts_logged(self, users):
        users.create(username="admin", password="password1", display_name="মালিক")
        users.authenticate("admin", "password1")
        with pytest.raises(BusinessRuleError):
            users.authenticate("admin", "bad")
        history = users.login_history()
        assert [h["succeeded"] for h in history] == [0, 1]

    def test_must_change_flag_round_trips(self, users):
        user_id = users.create(username="admin", password="password1", display_name="মালিক", must_change=True)
        assert users.authenticate("admin", "password1")["must_change"] is True
        users.set_password(user_id, "anotherpass")
        assert users.authenticate("admin", "anotherpass")["must_change"] is False


class TestRoles:
    def test_owner_inherits_manager_and_cashier(self):
        assert PERMISSIONS["cashier"] <= PERMISSIONS["manager"] <= PERMISSIONS["owner"]

    def test_cashier_cannot_manage_users(self):
        assert UserService.can("cashier", "pos.sell")
        assert not UserService.can("cashier", "user.manage")
        assert not UserService.can("cashier", "backup.restore")

    def test_manager_cannot_restore(self):
        assert UserService.can("manager", "backup.create")
        assert not UserService.can("manager", "backup.restore")

    def test_unknown_role_has_no_permissions(self):
        assert not UserService.can("ghost", "pos.sell")

    def test_last_owner_cannot_be_deactivated(self, users):
        user_id = users.create(username="admin", password="password1", display_name="মালিক", role="owner")
        with pytest.raises(BusinessRuleError):
            users.set_active(user_id, False)

    def test_last_owner_cannot_be_demoted(self, users):
        user_id = users.create(username="admin", password="password1", display_name="মালিক", role="owner")
        with pytest.raises(BusinessRuleError):
            users.set_role(user_id, "cashier")

    def test_second_owner_allows_demotion(self, users):
        first = users.create(username="one", password="password1", display_name="এক", role="owner")
        users.create(username="two", password="password1", display_name="দুই", role="owner")
        users.set_role(first, "manager")
        assert users.get(first)["role"] == "manager"

    def test_role_change_audited(self, users, db):
        users.create(username="one", password="password1", display_name="এক", role="owner")
        second = users.create(username="two", password="password1", display_name="দুই")
        users.set_role(second, "manager")
        rows = db.query("SELECT action FROM audit_logs WHERE entity_type='user'")
        assert "role_change" in [r["action"] for r in rows]
