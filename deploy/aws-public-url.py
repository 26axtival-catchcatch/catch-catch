"""Refresh only the public app URL on EC2; never emit environment secrets."""
from pathlib import Path
import sys
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from compose import LOCAL, read_env, write_private

request = urllib.request.Request(
    "http://169.254.169.254/latest/api/token", method="PUT",
    headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
)
token = urllib.request.urlopen(request, timeout=5).read().decode()
request = urllib.request.Request(
    "http://169.254.169.254/latest/meta-data/public-ipv4",
    headers={"X-aws-ec2-metadata-token": token},
)
ip = urllib.request.urlopen(request, timeout=5).read().decode()
settings = read_env(LOCAL / "stack.env")
settings.update({"PUBLIC_IP": ip, "APP_URL": f"https://{ip}"})
write_private(LOCAL / "stack.env", settings)
print(settings["APP_URL"])
