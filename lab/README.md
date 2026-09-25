# Train-Ticket fault lab

This fork is xlab-uiuc/train-ticket (FudanSELab/train-ticket plus flagd-guarded faults) with eight wiki faults made switchable and a steady traffic driver, for monitoring with Datadog. All faults start off.

| Fault | Switch | What changes when on | Evidence |
|---|---|---|---|
| F1 | `tt-feat-01` | ts-cancel-service reports the refund before running it; the refund lands 8 s later | cancel-service log order |
| F3 | `lab/fault.sh on F3` | train, basic, order and order-other services run a 1g heap inside a 640Mi limit | OOMKilled restarts |
| F7 | `tt-feat-07` | inside-payment pays through ts-payment-service with a 2 s budget; payment answers in 1.5–2.5 s | HTTP 500 on `inside_payment` |
| F12 | `tt-feat-12` | ts-order-other-service rejects cancels of K/Z/T-series orders touching Shanghai or Nanjing | `tt_status` 0, "station locked" |
| F14 | `tt-feat-14` | ts-basic-service prices economy seats at distance × 1 | `fare_anomaly` lines |
| F15 | `lab/fault.sh on F15` | the dashboard's nginx refuses API bodies over 300 bytes (bookings with food or consign) | HTTP 413 |
| F17 | `tt-feat-17` | ts-voucher-service sleeps 10 s in MySQL per lookup (from xlab) | `/getVoucher` ≥ 10 s |
| F22 | `tt-feat-22` | ts-voucher-service's lookup names a missing column, so Print Voucher shows "Empty. No data!" | HTTP 500 on `/getVoucher` |

Switch any fault with `lab/fault.sh on|off|status <F>` (kubectl pointed at the lab cluster; namespace `train-ticket`, override with `NAMESPACE`).

- Deploy: `lab/DEPLOYER.md` is an agent-executable runbook.
- Images: `.github/workflows/lab-images.yaml` builds the six changed services and the driver to `ghcr.io/rajagopal-epistak/*:lab` on push. New packages start private; make each one public once under the package's settings on GitHub.
- Build and test locally: `hack/lab/mvn.sh <module> test`, and `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab traffic-driver ts-voucher-service/tests -q`.
- `traffic-driver/autoquery/` is an unmodified copy of FudanSELab/train-ticket-auto-query at `9d5bc2d`.
