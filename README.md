# MeshBook

A GUI chat and blog network for Meshtastic LoRa networks.
MeshBook uses Meshtastic's public MQTT bridge to connect LoRa users across
the world. No server. No account. Just install and talk.

## What it does

- **Chat** with anyone running MeshBook through the Meshtastic LoRa network
- **Post** blog entries that persist across sessions
- **Search** all cached posts by name, location, or text
- **Find** users by name
- **Edit your profile** with searchable bio and tags
- **Browse a shared store** of text-only products from every user
- **Publish products** with categories and subcategories
- **Edit your own products** after publishing
- **Vouch** for good users, downvote bad ones
- **Direct message** anyone by clicking their name

## Install

### Windows

Open **cmd** and run:

```bat
curl -L -o install.bat https://raw.githubusercontent.com/jefboneta/meshbook/main/install.bat
install.bat
```

### Mac / Linux / Git Bash

```bash
curl -sL https://raw.githubusercontent.com/jefboneta/meshbook/main/install.sh | bash
```

The installer checks for Python 3.10+, installs `paho-mqtt`, downloads
`meshbook.py` into `~/meshbook/`, and prints the command to launch the app.

## MQTT credentials

For security, credentials are not stored in the source code. Set these
environment variables before launching the app:

```bash
export MESHBOOK_MQTT_USER="your-user"
export MESHBOOK_MQTT_PASS="your-password"
```

On Windows cmd:

```bat
set MESHBOOK_MQTT_USER=your-user
set MESHBOOK_MQTT_PASS=your-password
```

## Run

```bash
cd ~/meshbook
python meshbook.py
```

On first launch, click **Set Name** to pick a name and location.

## Commands in the GUI

- **Edit Profile** — update your name, location, searchable bio, and tags
- **Store** — browse or publish products with name, category, subcategory, type,
  serial number, price, and description/contact information. Select one of
  your listings and choose **Edit Product** to update it.
- **Refresh Peers** — update the user list
- **Send (Enter)** — send a chat message to the selected peer (or broadcast)
- **Post (Ctrl+Enter)** — publish a blog post to everyone
- **Search** — filter the feed and find peers by name, location, bio, or tags

## How it works

MeshBook uses Meshtastic LoRa radios and the public MQTT bridge as a shared
broadcast bus. Every running instance subscribes to the same topic on
`mqtt.meshtastic.org` and publishes its identity, posts, and chat messages
there. All state is stored locally in `meshbook_state.json`; there is no
central application server.
Store listings are saved to that state file as they arrive. When a client
connects, it requests the catalogs from currently connected peers; peers
respond by sending their saved listings.

The protocol is minimal:

```text
MB1|<command>|<seq>|<node_id>|<args>
```

Commands: `HELLO`, `PROFILE`, `POST`, `CHAT`, `VOUCH`, `PRODUCT`,
`STORE_SYNC`.

## Privacy

- Your messages are broadcast in plaintext on a public MQTT topic
- Your node ID is a random 8-character hex string, regenerated only if you
  delete `meshbook_state.json`
- Do not post anything you would not want a stranger to read

## License

MIT — see [LICENSE](LICENSE).
