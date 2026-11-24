# user_scripts changelog

| Version | Directory | Status | Notes |
|---------|-----------|--------|-------|
| v1 | `v1/` | Deployed | Initial version. |
| v2 | `v2-py312_and_hg702/` | Deployed | Python 3.12 and Mercurial 7.0.2 support. |
| v3 | `v3-disable-adb-killserver/` | Deployed | Disable adb kill-server. |
| v4 | `v4-python_fix/` | Deployed | Python fix. |
| v5 | `v5-python_runtime/` | Deployed | Python runtime update. |
| v6 | `v6-setup_sets_portrait/` | Not deployed | Superseded; perf team delivered a fix in-tree. Based on v5. |
| v7 | `v7-cdc_acm_detach_for_power_meters/` | Not deployed | Does not fully solve the problem — tests still fail because the race condition occurs during the tests, not just at setup. Based on v5. |
| v8 | `v8-disable-scrcpy-video/` | Superseded | Disables scrcpy video (`video: false`). Default as of PR #104. Based on v5. |
| v9 | `v9-disable-livevideo/` | Deployed | Also disables scrcpy live video (`liveVideo: false`) in addition to `video: false`. Default after testing on test-1 pool. Based on v8. |
| v10 | `v10-disable-network-capture/` | Configured for test-1 | Disables HyperExecute network capture and logging (`network: false`, `networkLog: false`) for Bug 2039991. Based on v9. |

Each version directory ships its own `hyperexecute.yaml.tmpl`. `job_config.return_config()` loads
the template from the version dir resolved by `ConfigurationLt.get_path_to_user_script_directory()`,
so a version can change the job-config shape (e.g. to disable scrcpy video) without code changes.
Placeholders use `string.Template` ($-style) syntax.
