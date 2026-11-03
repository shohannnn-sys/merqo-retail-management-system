# Known Issues & Limitations — Retvia

## Environment limitations (verified)

| ID | Limitation | Impact | Mitigation |
|---|---|---|---|
| L-01 | Sandbox blocks GitHub release assets and nodejs.org | Electron/native-Node stack cannot be built here | Chose Python/Qt stack (ADR-002) |
| L-02 | No `libGL` and no display server; apt blocked | Qt GUI cannot be rendered or screenshot-tested locally | GUI smoke tests + screenshots run on Windows CI |
| L-03 | No Windows OS in the sandbox | Cannot produce or install a Windows EXE locally | PyInstaller + Inno Setup run on `windows-latest` CI |
| L-04 | No physical thermal printer | Cannot verify real 58/80 mm print output | Verify PDF/raster geometry in CI; **physical test pending** |
| L-05 | No clean physical Windows PC | Cannot perform final user-acceptance install | CI silent install/uninstall test; **physical test pending** |

## Product limitations (accepted, disclosed)

| ID | Limitation | Rationale |
|---|---|---|
| P-01 | Offline licensing cannot guarantee absolute anti-piracy | Client-side checks are always bypassable with full machine control; defense-in-depth is used instead |
| P-02 | Name "Retvia" is not legally cleared | Only public web screening was possible; formal trademark/domain clearance is an owner action |
| P-03 | Single-business, single-machine per license | By design; multi-branch sync is out of scope for this product |

## Open defects

None recorded yet — no executable code has been written at this point. This
section will be updated as testing reveals defects.
