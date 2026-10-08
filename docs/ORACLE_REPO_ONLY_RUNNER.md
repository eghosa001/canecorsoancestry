# Oracle VM: GitHub Actions runner exclusive to Cane Corso Ancestry

## Goal and scope
Use the existing Oracle Linux ARM64 VM with the **dedicated** self-hosted runner registered to `eghosa001/canecorsoancestry` only. The VM currently hosts a runner registered to the private PULSE-CITY repository. A runner registered directly to CCA cannot be scheduled by another repository.

**Security:** CCA is a public repository. Self-hosted execution MUST remain restricted to manually authorized `workflow_dispatch` jobs on the protected `main` branch. The narrowly scoped PR job checks shell syntax only on a **GitHub-hosted Ubuntu runner**, not Oracle. Do not change to `pull_request` or `pull_request_target` on a self-hosted job; a malicious fork could compromise the VM. Avoid running arbitrary contributor code on this host. Use pinned trusted code for any future deployment.

## One-time enrollment on the VM
1. SSH in as `opc` through your normal secure channel. Do not upload or paste the private SSH key anywhere.
2. Open [CCA → Settings → Actions → Runners → New self-hosted runner](https://github.com/eghosa001/canecorsoancestry/settings/actions/runners/new). Select **Linux**, **ARM64**. Copy ONLY the short-lived registration token from the `--token` argument of GitHub's sample command. Do not share it in ChatGPT. It expires after a short time.
3. On the VM, after this branch is merged into `main`, run:

```bash
git clone --depth 1 https://github.com/eghosa001/canecorsoancestry.git "$HOME/cca-runner-setup"
cd "$HOME/cca-runner-setup"
bash scripts/oracle_runner/transfer_repo_runner.sh install
```

The script downloads GitHub's latest official Linux ARM64 runner, verifies its published SHA-256 digest, and registers `CCA-ORACLE` with label `cca-oracle`. The registration token is accepted at a hidden terminal prompt and is not committed or printed to build logs. It creates a separate systemd service under `opc` and does not touch the current PULSE-CITY service.

4. Go to **CCA → Actions → Oracle repo-only runner → Run workflow** on `main`. Verify the job succeeds. If it stays queued, ensure `CCA-ORACLE` appears Online with label `cca-oracle` in CCA Settings → Actions → Runners. Do not disable PULSE yet.

5. Only **after** the CCA workflow passes, on the VM run:

```bash
cd "$HOME/cca-runner-setup"
bash scripts/oracle_runner/transfer_repo_runner.sh retire-pulse --cca-workflow-passed
```

This stops and disables `actions.runner.eghosa001-PULSE-CITY.ORACLE.service` while leaving the new CCA runner running. Remove the old, offline `ORACLE` runner registration from **PULSE-CITY → Settings → Actions → Runners** so the old credentials are revoked. Do not remove the newer `CCA-ORACLE` runner from CCA.

## What success means
- CCA Actions shows one online `CCA-ORACLE` repository runner.
- The CCA **Oracle repo-only runner** manual workflow succeeds on `main`.
- No active PULSE-CITY runner service remains on the VM.
- PULSE-CITY shows no usable runner (the old registration is removed).
- Future VM workflows may be launched only through authorized CCA `main` workflows, with no PR code execution.
- No public ports, firewall settings, database credentials, or Django hosting cutover are changed by this registration work.

## Safeguards
- Do not replace the existing running PULSE service before CCA is tested. It is the existing remote recovery path.
- The VM has 1 ARM64 vCPU, 5.5 GiB RAM, and ~18 GiB free disk (diagnostic run 2026-10-08). Do not assume free CPU when builds run; no game-build runner should remain active alongside a production Django server.
- Oracle OCI security-list/NSG, local firewalld and reverse proxy must be reviewed separately before hosting Django. Do not open PostgreSQL or Gunicorn to the internet.
- Existing production Django stays on Northflank and Cloudflare until a separate staged hosting migration and live approval/media tests pass.
