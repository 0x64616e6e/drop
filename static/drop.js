// drop: in-browser decryption for end-to-end encrypted links, and one-time uploads.
// Encrypted download links carry #k=<key>&n=<name>&h=<sha256> after the path. Browsers never send
// the part after '#' to the server, so the server only ever holds and sends ciphertext:
// 12-byte AES-GCM nonce || ciphertext+tag, decrypted here with WebCrypto.
(() => {
  const $ = (id) => document.getElementById(id);
  const say = (msg, bad) => { const s = $("status"); if (s) { s.textContent = msg; s.className = bad ? "bad" : ""; } };
  const b64u = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), (c) => c.charCodeAt(0));
  const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  const gone = "This link is not available: it has been used, has expired, or never existed.";

  const dl = $("dl");
  if (dl) {
    const frag = new URLSearchParams(location.hash.slice(1));
    const k = frag.get("k"), n = frag.get("n"), h = frag.get("h");
    const btn = dl.querySelector("button");
    let name = "download.bin";
    if (n) { try { name = new TextDecoder().decode(b64u(n)); $("name").textContent = name; } catch (e) { /* keep default */ } }
    if (!k) { say("This link is missing its key (the part after #). Ask the sender for the complete link.", true); btn.disabled = true; }
    dl.addEventListener("submit", async (e) => {
      e.preventDefault(); btn.disabled = true;
      try {
        say("Downloading…");
        const pw = dl.querySelector("input[name=pass]");
        const body = new URLSearchParams(); if (pw) body.set("pass", pw.value);
        const r = await fetch(location.pathname, { method: "POST", body, headers: { "X-Drop-Api": "1" } });
        if (r.status === 403) { say("Wrong passphrase.", true); btn.disabled = false; return; }
        if (!r.ok) { say(gone, true); return; }
        const data = new Uint8Array(await r.arrayBuffer());
        say("Decrypting…");
        const key = await crypto.subtle.importKey("raw", b64u(k), "AES-GCM", false, ["decrypt"]);
        const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: data.subarray(0, 12) }, key, data.subarray(12));
        let note = "Decrypted.", bad = false;
        if (h) {
          const d = hex(await crypto.subtle.digest("SHA-256", plain));
          if (d === h) note = "Decrypted and verified (SHA-256 matches the sender's)."; else { note = "WARNING: checksum does not match the sender's."; bad = true; }
        }
        const url = URL.createObjectURL(new Blob([plain]));
        const a = document.createElement("a"); a.href = url; a.download = name; document.body.appendChild(a); a.click();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
        say(note + " Saved as " + name + ".", bad);
      } catch (err) {
        say("Could not decrypt: the key in this link does not match the file. For a few minutes you can retry from this device.", true);
        btn.disabled = false;
      }
    });
  }

  const ul = $("ul");
  if (ul) {
    const btn = ul.querySelector("button");
    ul.addEventListener("submit", (e) => {
      e.preventDefault();
      const f = $("file").files[0]; if (!f) return;
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", location.pathname);
      xhr.setRequestHeader("X-Filename", encodeURIComponent(f.name));
      const pw = $("pass"); if (pw) xhr.setRequestHeader("X-Drop-Pass", encodeURIComponent(pw.value));
      const prog = $("prog"); prog.hidden = false; prog.value = 0;
      xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) { prog.max = ev.total; prog.value = ev.loaded; say(Math.round((100 * ev.loaded) / ev.total) + "%"); } };
      xhr.onload = () => {
        if (xhr.status === 200) { say("Sent " + f.name + ". You can close this page."); ul.hidden = true; prog.hidden = true; }
        else if (xhr.status === 403) { say("Wrong passphrase.", true); btn.disabled = false; }
        else if (xhr.status === 413) { say(xhr.responseText || "The file is too large for this link.", true); btn.disabled = false; }
        else { say(xhr.status === 404 ? gone : "Upload failed (" + xhr.status + "). You can try again.", true); btn.disabled = xhr.status === 404; }
      };
      xhr.onerror = () => { say("Upload failed: connection lost. You can try again.", true); btn.disabled = false; };
      btn.disabled = true; say("Uploading…"); xhr.send(f);
    });
  }
})();
