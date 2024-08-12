# longport2beancount

Longport API to Beancount converter

## Usage

Example: fetch and convert orders of last 3 months.

```bash
export LONGPORT_APP_KEY=<app_key>
export LONGPORT_APP_SECRET=<app_secret>
export LONGPORT_ACCESS_TOKEN=<access_token>

pip3 install -r requirements.txt

python3 ./convert.py > last_3_months.beancount
```
