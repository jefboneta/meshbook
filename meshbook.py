#!/usr/bin/env python3
"""
MeshBook - GUI chat + blog over MQTT.
Single-window interface: user list, feed, search, input bar.
"""
import os
import sys
import json
import time
import uuid
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from collections import OrderedDict

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("ERROR: pip install paho-mqtt")
    sys.exit(1)

# ---------- Config ----------
STATE_FILE = os.environ.get('MESHBOOK_STATE', 'meshbook_state.json')
MQTT_HOST = 'mqtt.meshtastic.org'
MQTT_PORT = 1883
MQTT_USER = os.environ.get('MESHBOOK_MQTT_USER', '')
MQTT_PASS = os.environ.get('MESHBOOK_MQTT_PASS', '')
MQTT_TOPIC = os.environ.get('MESHBOOK_TOPIC', 'meshbook/v1/messages')
PROTOCOL = 'MB1'

BROADCAST_INTERVAL = 600
MAX_TEXT = 480
ONLINE_WINDOW = 900


# ---------- State ----------
class App:
    def __init__(self, root):
        self.root = root
        self.state = {
            'my_id': uuid.uuid4().hex[:8],
            'my_name': 'anonymous',
            'my_location': 'unknown',
            'my_bio': '',
            'my_tags': '',
            'my_seq': 0,
            'posts': {},
            'users': {},
            'reputation': {},
            'seen_seqs': set(),
        }
        self.lock = threading.Lock()
        self.mqtt_client = None
        self.target = None  # None = broadcast, else node_id
        self.feed_lines = []  # list of dicts for filtering
        self.peer_refresh_after = None

        self.load_state()
        self.build_ui()
        self.start_mqtt()
        self.schedule_announce()
        self.refresh_peers()

    # ---------- Persistence ----------

    def load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    loaded = json.load(f)
                self.state.update(loaded)
                self.state['seen_seqs'] = set(loaded.get('seen_seqs', []))
            except Exception as e:
                print(f"[state] load error: {e}")

    def save_state(self):
        with self.lock:
            to_save = dict(self.state)
            to_save['seen_seqs'] = list(self.state['seen_seqs'])
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(to_save, f, indent=2)
        except Exception:
            pass

    # ---------- UI ----------

    def build_ui(self):
        self.root.title(f"MeshBook — {self.state['my_name']}@{self.state['my_location']}")
        self.root.geometry("1000x680")

        # top bar
        top = tk.Frame(self.root, bg="#222")
        top.pack(fill=tk.X)
        tk.Label(top, text="MeshBook", bg="#222", fg="#8cf",
                 font=("Consolas", 14, "bold")).pack(side=tk.LEFT, padx=10, pady=6)

        self.status_label = tk.Label(top, text="connecting...", bg="#222", fg="#aaa",
                                     font=("Consolas", 10))
        self.status_label.pack(side=tk.LEFT, padx=10)

        tk.Button(top, text="Edit Profile", command=self.dialog_profile,
                  bg="#333", fg="#eee", relief=tk.FLAT).pack(side=tk.RIGHT, padx=4, pady=4)
        tk.Button(top, text="Refresh Peers", command=self.refresh_peers,
                  bg="#333", fg="#eee", relief=tk.FLAT).pack(side=tk.RIGHT, padx=4, pady=4)

        # main pane
        main = tk.Frame(self.root, bg="#111")
        main.pack(fill=tk.BOTH, expand=True)

        # left: peers
        left = tk.Frame(main, bg="#181818", width=220)
        left.pack(side=tk.LEFT, fill=tk.Y)
        left.pack_propagate(False)

        tk.Label(left, text="Peers", bg="#181818", fg="#8cf",
                 font=("Consolas", 11, "bold")).pack(anchor=tk.W, padx=8, pady=(8, 4))

        self.peer_list = tk.Listbox(left, bg="#0e0e0e", fg="#ddd",
                                    selectbackground="#2a4a6a",
                                    font=("Consolas", 10), relief=tk.FLAT,
                                    highlightthickness=0, activestyle="none")
        self.peer_list.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        self.peer_list.bind("<<ListboxSelect>>", self.on_peer_select)

        # right: feed + search + input
        right = tk.Frame(main, bg="#111")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # search bar
        search_row = tk.Frame(right, bg="#111")
        search_row.pack(fill=tk.X, padx=6, pady=(6, 0))
        tk.Label(search_row, text="Search:", bg="#111", fg="#8cf",
                 font=("Consolas", 10)).pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add('write', lambda *_: self.on_search_changed())
        entry = tk.Entry(search_row, textvariable=self.search_var,
                         bg="#1a1a1a", fg="#eee", insertbackground="#8cf",
                         font=("Consolas", 11), relief=tk.FLAT)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        tk.Button(search_row, text="Clear", command=lambda: self.search_var.set(""),
                  bg="#333", fg="#eee", relief=tk.FLAT).pack(side=tk.RIGHT)

        # feed
        self.feed = scrolledtext.ScrolledText(right, bg="#0a0a0a", fg="#ddd",
                                              font=("Consolas", 10),
                                              insertbackground="#8cf",
                                              relief=tk.FLAT, wrap=tk.WORD,
                                              state=tk.DISABLED)
        self.feed.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.feed.tag_config("self", foreground="#8cf")
        self.feed.tag_config("peer", foreground="#eee")
        self.feed.tag_config("post", foreground="#cf8")
        self.feed.tag_config("chat", foreground="#fc8")
        self.feed.tag_config("time", foreground="#666")
        self.feed.tag_config("system", foreground="#888", font=("Consolas", 9, "italic"))

        # target label
        self.target_label = tk.Label(right, text="→ broadcast",
                                     bg="#111", fg="#8cf", font=("Consolas", 10))
        self.target_label.pack(anchor=tk.W, padx=8)

        # input row
        input_row = tk.Frame(right, bg="#111")
        input_row.pack(fill=tk.X, padx=6, pady=6)

        self.input = tk.Text(input_row, height=3, bg="#1a1a1a", fg="#eee",
                             insertbackground="#8cf", font=("Consolas", 11),
                             relief=tk.FLAT, wrap=tk.WORD)
        self.input.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.input.bind("<Return>", self.on_enter)
        self.input.bind("<Shift-Return>", lambda e: None)
        self.input.bind("<Control-Return>", self.on_ctrl_enter)

        btn_frame = tk.Frame(input_row, bg="#111")
        btn_frame.pack(side=tk.RIGHT, padx=(6, 0))
        tk.Button(btn_frame, text="Send (Enter)", command=self.send_chat,
                  bg="#2a5a3a", fg="#eee", relief=tk.FLAT, width=14).pack(pady=2)
        tk.Button(btn_frame, text="Post (Ctrl+Enter)", command=self.send_post,
                  bg="#3a4a6a", fg="#eee", relief=tk.FLAT, width=14).pack(pady=2)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_peer_select(self, event):
        sel = self.peer_list.curselection()
        if not sel:
            return
        line = self.peer_list.get(sel[0])
        # first entry is "→ broadcast"
        if line.startswith("→"):
            self.target = None
            self.target_label.config(text="→ broadcast")
            return
        # parse "<nodeid>  name@loc"
        parts = line.split()
        if parts:
            self.target = parts[0]
            self.target_label.config(text=f"→ {line.strip()}")

    def add_feed(self, kind, text, name=None, ts=None):
        if ts is None:
            ts = time.time()
        self.feed_lines.append({
            'kind': kind, 'text': text, 'name': name, 'ts': ts,
        })
        self.render_feed()

    def render_feed(self):
        query = self.search_var.get().strip().lower()
        self.feed.config(state=tk.NORMAL)
        self.feed.delete("1.0", tk.END)
        for entry in self.feed_lines[-500:]:
            if query:
                hay = f"{entry.get('name','')} {entry['text']}".lower()
                if query not in hay:
                    continue
            stamp = time.strftime("%H:%M", time.localtime(entry['ts']))
            self.feed.insert(tk.END, f"[{stamp}] ", "time")
            name = entry.get('name') or 'system'
            tag = entry['kind']
            self.feed.insert(tk.END, f"{name}: ", tag)
            self.feed.insert(tk.END, entry['text'] + "\n", tag)
        self.feed.see(tk.END)
        self.feed.config(state=tk.DISABLED)

    def on_search_changed(self):
        self.render_feed()
        self.refresh_peers()

    # ---------- Protocol ----------

    def make_frame(self, cmd, args=''):
        with self.lock:
            self.state['my_seq'] = (self.state['my_seq'] + 1) & 0xffff
            seq = f"{self.state['my_seq']:04x}"
            my_id = self.state['my_id']
        return f"{PROTOCOL}|{cmd}|{seq}|{my_id}|{args}"

    def parse_frame(self, text):
        if not text.startswith(PROTOCOL + '|'):
            return None
        parts = text[len(PROTOCOL) + 1:].split('|', 3)
        if len(parts) < 3:
            return None
        return {'cmd': parts[0], 'seq': parts[1],
                'from': parts[2], 'args': parts[3] if len(parts) > 3 else ''}

    def publish(self, frame):
        if self.mqtt_client is None:
            return
        try:
            self.mqtt_client.publish(MQTT_TOPIC, frame)
        except Exception:
            pass

    def handle_frame(self, src_id, f):
        cmd = f['cmd']
        args = f['args']
        seq = f['seq']
        now = time.time()

        seq_key = f"{src_id}/{seq}"
        with self.lock:
            if seq_key in self.state['seen_seqs']:
                return
            self.state['seen_seqs'].add(seq_key)
            if len(self.state['seen_seqs']) > 5000:
                self.state['seen_seqs'] = set(list(self.state['seen_seqs'])[-2000:])

        if cmd == 'HELLO':
            parts = args.split('|', 1)
            name = parts[0] if parts else 'anonymous'
            loc = parts[1] if len(parts) > 1 else 'unknown'
            with self.lock:
                self.state['users'][src_id] = {
                    'name': name, 'location': loc, 'last_seen': now,
                }
            if src_id != self.state['my_id']:
                self.add_feed('system', f"{name}@{loc} joined ({src_id})")
                self.refresh_peers()

        elif cmd == 'PROFILE':
            try:
                profile = json.loads(args)
            except (TypeError, json.JSONDecodeError):
                return
            if not isinstance(profile, dict):
                return
            name = str(profile.get('name', 'anonymous')).strip() or 'anonymous'
            location = str(profile.get('location', 'unknown')).strip() or 'unknown'
            bio = str(profile.get('bio', '')).strip()
            tags = str(profile.get('tags', '')).strip()
            with self.lock:
                self.state['users'][src_id] = {
                    'name': name, 'location': location,
                    'bio': bio, 'tags': tags, 'last_seen': now,
                }
            if src_id != self.state['my_id']:
                self.refresh_peers()

        elif cmd == 'POST':
            parts = args.split('|', 1)
            if len(parts) < 2:
                return
            post_id, text = parts
            full_id = f"{src_id}/{post_id}"
            with self.lock:
                if full_id in self.state['posts']:
                    return
                author = self.state['users'].get(src_id, {})
                self.state['posts'][full_id] = {
                    'author': src_id,
                    'name': author.get('name', 'unknown'),
                    'location': author.get('location', '?'),
                    'text': text,
                    'ts': now,
                }
            self.add_feed('post', text, name=author.get('name', src_id[:4]))

        elif cmd == 'CHAT':
            with self.lock:
                name = self.state['users'].get(src_id, {}).get('name', src_id[:4])
            # ignore if the message is addressed to someone else
            parts = args.split('|', 1)
            if len(parts) == 2:
                to_id, text = parts
                if to_id != '*' and to_id != self.state['my_id']:
                    return
            else:
                text = args
            self.add_feed('chat', text, name=name)

        elif cmd == 'VOUCH':
            parts = args.split('|', 1)
            if len(parts) < 2:
                return
            target, delta = parts
            try:
                delta = int(delta)
            except ValueError:
                return
            with self.lock:
                self.state['reputation'][target] = \
                    self.state['reputation'].get(target, 0) + delta
            self.add_feed('system', f"vouch: {src_id[:4]} -> {target[:4]} {delta:+d}")
            self.refresh_peers()

    # ---------- MQTT ----------

    def on_connect(self, client, userdata, flags, rc):
        client.subscribe(MQTT_TOPIC)
        self.status_label.config(text=f"connected to {MQTT_HOST}")
        self.announce()

    def on_message(self, client, userdata, msg):
        try:
            text = msg.payload.decode('utf-8', errors='replace')
        except Exception:
            return
        f = self.parse_frame(text)
        if not f:
            return
        # ignore our own messages
        if f['from'] == self.state['my_id']:
            return
        self.handle_frame(f['from'], f)

    def start_mqtt(self):
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        try:
            self.mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
            threading.Thread(target=self.mqtt_client.loop_forever,
                             daemon=True).start()
        except Exception as e:
            self.status_label.config(text=f"mqtt error: {e}")

    def announce(self):
        with self.lock:
            profile = {
                'name': self.state['my_name'],
                'location': self.state['my_location'],
                'bio': self.state.get('my_bio', ''),
                'tags': self.state.get('my_tags', ''),
            }
            name = profile['name']
            loc = profile['location']
        self.publish(self.make_frame('HELLO', f"{name}|{loc}"))
        self.publish(self.make_frame('PROFILE', json.dumps(profile, ensure_ascii=True)))
        # mark ourselves as online
        with self.lock:
            self.state['users'][self.state['my_id']] = {
                'name': name, 'location': loc, 'last_seen': time.time(),
                'bio': profile['bio'], 'tags': profile['tags'],
            }

    def schedule_announce(self):
        self.announce()
        self.root.after(BROADCAST_INTERVAL * 1000, self.schedule_announce)

    # ---------- UI actions ----------

    def dialog_profile(self):
        win = tk.Toplevel(self.root)
        win.title("Edit profile")
        win.geometry("420x260")
        win.configure(bg="#1a1a1a")

        tk.Label(win, text="Name:", bg="#1a1a1a", fg="#eee").pack(anchor=tk.W, padx=10, pady=(10, 0))
        name_var = tk.StringVar(value=self.state['my_name'])
        tk.Entry(win, textvariable=name_var, bg="#222", fg="#eee",
                 insertbackground="#8cf").pack(fill=tk.X, padx=10)

        tk.Label(win, text="Location:", bg="#1a1a1a", fg="#eee").pack(anchor=tk.W, padx=10, pady=(8, 0))
        loc_var = tk.StringVar(value=self.state['my_location'])
        tk.Entry(win, textvariable=loc_var, bg="#222", fg="#eee",
                 insertbackground="#8cf").pack(fill=tk.X, padx=10)

        tk.Label(win, text="Bio / searchable information:", bg="#1a1a1a",
                 fg="#eee").pack(anchor=tk.W, padx=10, pady=(8, 0))
        bio_var = tk.StringVar(value=self.state.get('my_bio', ''))
        tk.Entry(win, textvariable=bio_var, bg="#222", fg="#eee",
                 insertbackground="#8cf").pack(fill=tk.X, padx=10)

        tk.Label(win, text="Tags (comma-separated):", bg="#1a1a1a",
                 fg="#eee").pack(anchor=tk.W, padx=10, pady=(8, 0))
        tags_var = tk.StringVar(value=self.state.get('my_tags', ''))
        tk.Entry(win, textvariable=tags_var, bg="#222", fg="#eee",
                 insertbackground="#8cf").pack(fill=tk.X, padx=10)

        def save():
            self.state['my_name'] = name_var.get().strip() or 'anonymous'
            self.state['my_location'] = loc_var.get().strip() or 'unknown'
            self.state['my_bio'] = bio_var.get().strip()[:200]
            self.state['my_tags'] = tags_var.get().strip()[:200]
            self.save_state()
            self.announce()
            self.root.title(f"MeshBook — {self.state['my_name']}@{self.state['my_location']}")
            self.add_feed('system', f"profile updated: {self.state['my_name']}@{self.state['my_location']}")
            win.destroy()

        tk.Button(win, text="Save", command=save, bg="#2a5a3a", fg="#eee",
                  relief=tk.FLAT).pack(pady=10)

    def send_chat(self):
        text = self.input.get("1.0", tk.END).strip()
        if not text:
            return
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT]
        target = self.target or '*'
        self.publish(self.make_frame('CHAT', f"{target}|{text}"))
        label = self.target if self.target else "broadcast"
        self.add_feed('self', text, name=f"me -> {label}")
        self.input.delete("1.0", tk.END)

    def send_post(self):
        text = self.input.get("1.0", tk.END).strip()
        if not text:
            return
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT]
        with self.lock:
            self.state['my_seq'] = (self.state['my_seq'] + 1) & 0xffff
            post_id = f"{self.state['my_seq']:04x}"
        full_id = f"{self.state['my_id']}/{post_id}"
        with self.lock:
            self.state['posts'][full_id] = {
                'author': self.state['my_id'],
                'name': self.state['my_name'],
                'location': self.state['my_location'],
                'text': text,
                'ts': time.time(),
            }
        self.publish(self.make_frame('POST', f"{post_id}|{text}"))
        self.add_feed('self', f"[post] {text}", name=self.state['my_name'])
        self.input.delete("1.0", tk.END)

    def on_enter(self, event):
        self.send_chat()
        return "break"

    def on_ctrl_enter(self, event):
        self.send_post()
        return "break"

    def refresh_peers(self):
        now = time.time()
        self.peer_list.delete(0, tk.END)
        self.peer_list.insert(tk.END, "→ broadcast")
        with self.lock:
            users = dict(self.state['users'])
        query = self.search_var.get().strip().lower()
        # sort by online then name
        items = []
        for nid, u in users.items():
            online = (now - u.get('last_seen', 0)) < ONLINE_WINDOW
            items.append((not online, u.get('name', ''), nid, u))
        items.sort()
        for _, name, nid, u in items:
            searchable = ' '.join([
                nid, u.get('name', ''), u.get('location', ''),
                u.get('bio', ''), u.get('tags', ''),
            ]).lower()
            if query and query not in searchable:
                continue
            dot = "●" if (now - u.get('last_seen', 0)) < ONLINE_WINDOW else " "
            rep = self.state['reputation'].get(nid, 0)
            label = f"{nid}  {dot} {u.get('name','?')}@{u.get('location','?')}"
            details = ' '.join(filter(None, [u.get('bio', ''), u.get('tags', '')]))
            if details:
                label += f" — {details}"
            if rep:
                label += f" ({rep:+d})"
            self.peer_list.insert(tk.END, label)
        if self.peer_refresh_after is not None:
            self.root.after_cancel(self.peer_refresh_after)
        self.peer_refresh_after = self.root.after(15000, self.refresh_peers)

    def on_close(self):
        self.save_state()
        try:
            if self.mqtt_client:
                self.mqtt_client.disconnect()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == '__main__':
    main()