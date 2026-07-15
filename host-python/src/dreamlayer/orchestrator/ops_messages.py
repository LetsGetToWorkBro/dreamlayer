"""ops_messages — extracted Orchestrator method cluster (behaviour-preserving).

A mixin the Orchestrator inherits; every method here still runs on the
coordinator instance (shared self), so all self.<engine> attributes,
the bridge, and the privacy gate resolve exactly as before. No logic
was changed in the move.
"""
from __future__ import annotations

from ._ops_host import OpsHost

from ..hud import cards
from ._ops_helpers import _default_http_get


class MessagesOps(OpsHost):

    # -- live message pop-ups (texts/emails flash on the glasses) --------

    def set_message_notifications(self, on: bool = True) -> None:
        """Both channels at once (convenience)."""
        self.notify_texts = self.notify_emails = on


    def set_text_notifications(self, on: bool = True) -> None:
        self.notify_texts = on


    def set_email_notifications(self, on: bool = True) -> None:
        self.notify_emails = on


    def poll_messages(self, items: list, now: float | None = None) -> list:
        """Turn newly-arrived *incoming* messages into glasses pop-ups.

        `items` is the Brain's recent-messages feed (fetched by the hub from
        /dreamlayer/messages/recent). Only messages newer than the last seen,
        and not sent by you, pop up — texts and emails gated separately, each
        silenced by the Privacy Veil. Emails use the Brain's `summary` when it
        provided one (they run long). Returns the cards it flashed. Idempotent:
        re-polling the same feed shows nothing new.
        """
        cards_sent = []
        newest = self._msg_seen_ts
        for m in sorted(items, key=lambda x: x.get("ts", 0)):
            ts = m.get("ts", 0)
            if ts <= self._msg_seen_ts or m.get("from_me"):
                newest = max(newest, ts)
                continue
            newest = max(newest, ts)
            is_email = m.get("channel") == "email"
            if not (self.notify_emails if is_email else self.notify_texts):
                continue
            if not self.privacy.allow_capture() or self.focus_active():
                continue
            if is_email:
                body = m.get("summary") or (f"{m['subject']} — {m.get('text','')}"
                                            if m.get("subject") else m.get("text", ""))
            else:
                body = m.get("text", "")
            card = cards.message_notification(m.get("who", ""), body,
                                              m.get("channel", "imessage"))
            self.bridge.send_card(card, event="message")
            cards_sent.append(card)
        self._msg_seen_ts = newest
        return cards_sent


    def poll_messages_once(self, http_get=None) -> list:
        """Fetch the Brain's message feed once and flash anything new. A no-op
        with no Mac mini paired (there's no message source without it — iOS
        can't read your texts, so the Mac is the bridge)."""
        if not self.mac_mini_connected or not self.brain_url:
            return []
        getter = http_get or _default_http_get
        try:
            data = getter(self.brain_url.rstrip("/") + "/dreamlayer/messages/recent",
                          self.brain_token)
        except Exception:
            return []
        items = data.get("items", []) if isinstance(data, dict) else []
        return self.poll_messages(items)


    def start_message_polling(self, interval: float = 8.0, http_get=None) -> None:
        """Run poll_messages_once() on a background timer so pop-ups fire on
        their own. Idempotent; stop with stop_message_polling()."""
        if self._msg_poll_stop is not None:
            return
        import threading
        self._msg_poll_stop = threading.Event()

        def loop():
            while not self._msg_poll_stop.wait(interval):
                try:
                    self.poll_messages_once(http_get)
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True).start()


    def stop_message_polling(self) -> None:
        if self._msg_poll_stop is not None:
            self._msg_poll_stop.set()
            self._msg_poll_stop = None
