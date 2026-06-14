# Installing the Kelvinator Home Comfort Add-on

## Quick Start (the easy way)

### 1. Build the add-on package

From this directory, run:

```bash
make build
```

This creates `release/kelvinator-home-comfort-1.0.0.tar.gz` — a single file you can copy anywhere.

To clean up and start fresh:

```bash
make clean
```

### 2. Copy to your Home Assistant machine

**Option A — If you can SSH into HA:**

```bash
# Copy the tarball over
scp release/kelvinator-home-comfort-1.0.0.tar.gz root@homeassistant.local:/tmp/

# On the HA machine, unpack it into the local addons folder
ssh root@homeassistant.local
mkdir -p /addons/kelvinator-home-comfort
cd /addons/kelvinator-home-comfort
tar xzf /tmp/kelvinator-home-comfort-1.0.0.tar.gz
```

**Option B — Using the Samba / SSH add-on in HA:**

1. Install the **Samba share** or **SSH & Web Terminal** add-on from the official add-on store
2. Copy the tarball into `/addons/` (Samba) or use `scp` (SSH)
3. Unpack as shown above

**Option C — If running HA in Docker (bare metal):**

```bash
# The local addons dir is typically:
mkdir -p /usr/share/hassio/addons/local/kelvinator-home-comfort
cd /usr/share/hassio/addons/local/kelvinator-home-comfort
tar xzf /path/to/kelvinator-home-comfort-1.0.0.tar.gz
```

### 3. Install in Home Assistant

1. Open Home Assistant → **Settings** → **Add-ons**
2. Click **Add-on Store** (bottom right)
3. Click the **⋮** menu (top right) → **Check for updates**
4. Click the **⋮** menu → **Local add-ons**
5. You should see **"Kelvinator Home Comfort"** — click it
6. Click **Install** — this builds the Docker image (first time may take ~2 min)

### 4. Configure

Go to the **Configuration** tab and fill in at minimum:

```yaml
username: "your_kelvinator_email_or_phone"
password: "your_kelvinator_password"
country_code: "61"   # 61=AU, 64=NZ
```

Leave the MQTT fields blank — the add-on auto-detects the HA internal broker.

### 5. Start

Click **Start**, then go to the **Log** tab to watch the bridge come up.

Expected log output:

```
=== Kelvinator Home Comfort Add-on ===
MQTT Broker: core-mosquitto:1883
Poll Interval: 30s
Connecting to MQTT at core-mosquitto:1883
MQTT connected [rc=0]
Discovering BroadLink devices on LAN...
Connected to Living Room AC [AA:BB:CC:DD:EE:FF] type=0x4E2A
Device Living Room AC [AA:BB:CC:DD:EE:FF]: power=False temp=24°C
Registered climate: Living Room AC
Starting poll loop (interval=30s)
```

### 6. Verify devices appear

- Go to **Settings** → **Devices & Services** → **MQTT**
- You should see a **Climate** entity and several **Sensor** / **Switch** entities for each AC unit
- Add the climate card to your dashboard — you now have full control

---

## Requirements

| Requirement | Notes |
|---|---|
| Home Assistant OS, Supervised, or Container with Supervisor | The add-on system needs Supervisor |
| MQTT broker | Mosquitto add-on (auto-detected if using HA internal broker) |
| Kelvinator AC unit on same LAN | The add-on discovers devices via UDP broadcast |
| BroadLink DNA-compatible Wi-Fi module | Built into the Kelvinator unit |

---

## Troubleshooting

### "No BroadLink devices discovered on LAN"

- Make sure the AC unit is powered on and connected to Wi-Fi via the Kelvinator app
- The AC and your HA machine must be on the **same subnet** (UDP broadcast doesn't cross VLANs)
- Try increasing the discovery timeout in the code if your network is slow

### "Login failed" in logs

- Double-check your username/password — these are the same credentials you use in the Kelvinator phone app
- If you use a phone number, make sure `country_code` matches (61 = Australia, 64 = New Zealand)

### Add-on doesn't appear in Local add-ons

- Make sure the folder structure is correct — `config.yaml` **must** be at the root of the addon folder
- Go to **Add-on Store** → **⋮** → **Check for updates**, then **Local add-ons** again

### Devices appear but are "unavailable"

- The AC unit may have gone to sleep or lost Wi-Fi. The addon polls every 30s and will recover.
- Check the **Log** tab for connection errors

---

## Uninstalling

1. **Settings** → **Add-ons** → **Kelvinator Home Comfort** → **Uninstall**
2. Delete the addon folder from `/addons/kelvinator-home-comfort/` on the HA machine
