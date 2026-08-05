"""Fixture for `semgrep --test --config .semgrep/dreamlayer.yml`.

WHY THIS FILE EXISTS
--------------------
The six rules in dreamlayer.yml report zero findings against this repository,
which is the intended state — and is byte-for-byte what they would report if a
pattern stopped matching. A metavariable rename, a typo in the $VAL regex, or a
semgrep syntax change would each turn the privacy contract off and leave the
workflow's SARIF output looking exactly as clean as it does today. That is the
failure this codebase keeps meeting (CLAUDE.md #1): a green check that examined
nothing.

`semgrep --test` reads the annotations below. A positive one names a rule and
asserts the NEXT line must be flagged by it; a negative one asserts the next
line must not be. So this file fails loudly when a rule stops firing, which is
the only thing the scan itself cannot tell you.

(The annotation keywords are not spelled out in this docstring on purpose —
semgrep parses them anywhere in the file, comment or not, and a prose mention
is read as a real assertion naming a rule that does not exist.)

Nothing here is imported or executed. It is deliberately excluded from ruff and
mypy — it contains, on purpose, exactly the code those tools exist to reject.
"""
import pickle
import subprocess

import httpx
import requests
import yaml

log = None
user_name = email = token = transcript = juno_text = None
rescue = queryset = context = session_id = None
contact_name = None
answer = None
auth = None
authorization = None
content = None
cookie = None
cue = None
juno_answer = None
juno_auth = None
juno_authorization = None
juno_content = None
juno_cookie = None
juno_cue = None
juno_key = None
juno_message_body = None
juno_prompt = None
juno_query = None
juno_reply = None
juno_session = None
juno_text = None
key = None
message_body = None
prompt = None
query = None
reply = None
session = None
text = None
the_address_field = None
the_apikey_field = None
the_caption_field = None
the_contact_field = None
the_credential_field = None
the_email_field = None
the_embedding_field = None
the_name_field = None
the_passcode_field = None
the_passphrase_field = None
the_password_field = None
the_phone_field = None
the_secret_field = None
the_ssn_field = None
the_summary_field = None
the_token_field = None
the_transcript_field = None
exc = cmd = path = payload = fh = untrusted = None


# --- pii-in-log-message ------------------------------------------------------
# The four interpolation shapes the rule claims to cover. Each is a real way the
# message string reaches record.getMessage() unredacted.

# ruleid: pii-in-log-message
log.info(f"reply={juno_text}")
# ruleid: pii-in-log-message
log.warning("to=%s" % email)
# ruleid: pii-in-log-message
log.error("t={}".format(transcript))
# ruleid: pii-in-log-message
log.info("name=%s", user_name)

# The exclusions, which matter as much as the matches: a rule that fires on
# everything gets switched off. These are the words logging_setup._is_sensitive
# deliberately does NOT treat as sensitive — the anchored KEYS must not match as
# substrings, or `session_id` and `context` become unloggable and the contract
# becomes noise somebody silences.

# ok: pii-in-log-message
log.info("rescue=%s", rescue)
# ok: pii-in-log-message
log.info("queryset=%s", queryset)
# ok: pii-in-log-message
log.info("context=%s", context)
# ok: pii-in-log-message
log.info("session_id=%s", session_id)

# The one allowlisted dunder. `type(exc).__name__` is an exception CLASS name,
# never PII, and logging it instead of `exc` is the careful choice — an
# exception's message can carry a path or captured content. The AST guard has
# allowlisted it since it was written; this rule flagged four deliberate uses
# before the lookahead was added, and a regression would flag them again.
# ok: pii-in-log-message
log.error("failed: %s", type(exc).__name__)

# ...but only the dunder. Every person-name field still trips, which is the
# distinction the lookahead has to keep: `(?:.*\.)?__name__$`, not "any dunder".
# ruleid: pii-in-log-message
log.info("who=%s", contact_name)


# --- eval-exec ---------------------------------------------------------------
# ruleid: eval-exec
eval(untrusted)
# ruleid: eval-exec
exec(untrusted)


# --- subprocess-shell-true ---------------------------------------------------
# ruleid: subprocess-shell-true
subprocess.run(cmd, shell=True)
# ruleid: subprocess-shell-true
subprocess.Popen(cmd, shell=True)
# ruleid: subprocess-shell-true
subprocess.check_output(cmd, shell=True)
# ok: subprocess-shell-true
subprocess.run(["ls", "-l"])


# --- yaml-unsafe-load --------------------------------------------------------
# ruleid: yaml-unsafe-load
yaml.load(payload)
# The pattern-not arms are the whole point of this rule: safe_load and an
# explicit SafeLoader must stay silent, or every legitimate config read is a
# finding and the rule gets disabled.
# ok: yaml-unsafe-load
yaml.load(payload, Loader=yaml.SafeLoader)
# ok: yaml-unsafe-load
yaml.safe_load(payload)


# --- requests-verify-false ---------------------------------------------------
# ruleid: requests-verify-false
requests.get("https://example.invalid", verify=False)
# ruleid: requests-verify-false
httpx.post("https://example.invalid", verify=False)
# ok: requests-verify-false
requests.get("https://example.invalid")


# --- pickle-loads ------------------------------------------------------------
# ruleid: pickle-loads
pickle.loads(payload)
# ruleid: pickle-loads
pickle.load(fh)


# --- pii-in-log-message: every ROOT and every KEY, one case each --------------
# Written after a mutation SURVIVED an earlier draft of this fixture. That draft
# had four hand-picked leaks, and dropping `reply` from the anchored KEYS group
# changed nothing — its `reply=` case interpolated `juno_text`, which the rule
# still caught on the `_text$` key. The fixture looked like it covered the regex
# and covered four of thirty entries; the same shape of hole it exists to find.
#
# So: one case per entry, each naming ONLY that entry, so deleting any single
# word from the pattern fails a case that names it.

# ROOTS match as substrings — deliberately, so `user_email` and `emailAddr` both
# trip. Each is embedded rather than used bare, which is what the .* arms claim.

# ruleid: pii-in-log-message
log.info("v=%s", the_name_field)
# ruleid: pii-in-log-message
log.info("v=%s", the_email_field)
# ruleid: pii-in-log-message
log.info("v=%s", the_phone_field)
# ruleid: pii-in-log-message
log.info("v=%s", the_address_field)
# ruleid: pii-in-log-message
log.info("v=%s", the_token_field)
# ruleid: pii-in-log-message
log.info("v=%s", the_secret_field)
# ruleid: pii-in-log-message
log.info("v=%s", the_password_field)
# ruleid: pii-in-log-message
log.info("v=%s", the_passphrase_field)
# ruleid: pii-in-log-message
log.info("v=%s", the_credential_field)
# ruleid: pii-in-log-message
log.info("v=%s", the_apikey_field)
# ruleid: pii-in-log-message
log.info("v=%s", the_transcript_field)
# ruleid: pii-in-log-message
log.info("v=%s", the_embedding_field)
# ruleid: pii-in-log-message
log.info("v=%s", the_contact_field)
# ruleid: pii-in-log-message
log.info("v=%s", the_summary_field)
# ruleid: pii-in-log-message
log.info("v=%s", the_caption_field)
# ruleid: pii-in-log-message
log.info("v=%s", the_passcode_field)
# ruleid: pii-in-log-message
log.info("v=%s", the_ssn_field)

# KEYS are ANCHORED — exact, or a `_<key>` suffix. Bare and suffixed forms both,
# because the `(^|_)` alternation is two claims and a rewrite can lose either.

# ruleid: pii-in-log-message
log.info("v=%s", text)
# ruleid: pii-in-log-message
log.info("v=%s", juno_text)
# ruleid: pii-in-log-message
log.info("v=%s", content)
# ruleid: pii-in-log-message
log.info("v=%s", juno_content)
# ruleid: pii-in-log-message
log.info("v=%s", prompt)
# ruleid: pii-in-log-message
log.info("v=%s", juno_prompt)
# ruleid: pii-in-log-message
log.info("v=%s", reply)
# ruleid: pii-in-log-message
log.info("v=%s", juno_reply)
# ruleid: pii-in-log-message
log.info("v=%s", query)
# ruleid: pii-in-log-message
log.info("v=%s", juno_query)
# ruleid: pii-in-log-message
log.info("v=%s", answer)
# ruleid: pii-in-log-message
log.info("v=%s", juno_answer)
# ruleid: pii-in-log-message
log.info("v=%s", cue)
# ruleid: pii-in-log-message
log.info("v=%s", juno_cue)
# ruleid: pii-in-log-message
log.info("v=%s", key)
# ruleid: pii-in-log-message
log.info("v=%s", juno_key)
# ruleid: pii-in-log-message
log.info("v=%s", auth)
# ruleid: pii-in-log-message
log.info("v=%s", juno_auth)
# ruleid: pii-in-log-message
log.info("v=%s", authorization)
# ruleid: pii-in-log-message
log.info("v=%s", juno_authorization)
# ruleid: pii-in-log-message
log.info("v=%s", session)
# ruleid: pii-in-log-message
log.info("v=%s", juno_session)
# ruleid: pii-in-log-message
log.info("v=%s", cookie)
# ruleid: pii-in-log-message
log.info("v=%s", juno_cookie)
# ruleid: pii-in-log-message
log.info("v=%s", message_body)
# ruleid: pii-in-log-message
log.info("v=%s", juno_message_body)
