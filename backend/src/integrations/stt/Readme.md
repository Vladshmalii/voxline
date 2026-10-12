# Speech-to-text adapters

One `base.py` contract, one module per recogniser, one registry
(`SttAdapters`) the engine resolves through. Adding a backend is an enum value
in `src/common/enums/engine.py`, an adapter module here, and a DB row — never a
branch in the engine.

Current adapters:

| adapter      | transport                        | streams during speech | reports language |
|--------------|----------------------------------|-----------------------|------------------|
| `qwen3_asr`  | vLLM realtime WebSocket          | yes                   | yes (preamble)   |
| `voxtral`    | same route, different dialect    | no (after commit)     | **no**           |
| `cartesia`   | Cartesia Live WebSocket (hosted) | yes                   | **no** (not documented) |
| `deepgram`   | Deepgram Listen, via its SDK     | yes                   | **no**, unless `language=multi` |
| `openrouter` | batch HTTP upload per utterance  | **no** (one request per segment) | **no**, unless the row asks for `verbose_json` (verified on `whisper-large-v3`) |

Both hosted adapters *read* a reported language when one arrives and expose it
as `detected_language`; what they do not do is claim one in their capabilities,
because neither vendor documents detection on a plain model. An organization
that sees the field on its own traffic turns `reports_language` on from its
model row — that is the mechanism, and it is one row, not a release.

Protocol divergences live in each adapter's `SttCapabilities` declaration
(overridable per organization from the model row), not in client code — see
`src/application/engine/capabilities.py` for the measured comparison table.

The self-hosted pair is billed by the GPU-second, so they stream only while the
VAD gate is open; the hosted pair is billed by the minute of audio on a session
the vendor's own endpointing runs on, so those adapters stream the whole call
and let a finalize command close an utterance. Their capability values also
differ in provenance: the vLLM ones were measured against live deployments,
Cartesia's and Deepgram's are read off vendor documentation and are the first
thing to re-check against real traffic.

`openrouter` is the odd one out and deliberately so: it is an aggregator, not a
recogniser. One key and one host buy the whole transcription catalogue
(`openai/whisper-large-v3`, `google/chirp-3`, …) at the price of the only
non-streaming transport here — `POST /audio/speech`'s sibling
`/audio/transcriptions` takes one complete utterance as base64 and answers with
the whole transcript, so segments are cut by Pipecat's `SegmentedSTTService` at
VAD stops and nothing arrives while the caller is still talking. Use it to reach
a model no other adapter fronts, or to try one before committing to a direct
integration; for a language the pipeline runs hot, a streaming adapter is the
better seat. Its request surface (`temperature`, `response_format`, a `provider`
routing block, per-vendor passthrough) is a row edit via
`provider.options["body"]`, and `options["app_url"]` / `options["app_name"]`
label the tenant's traffic in OpenRouter's dashboard.

Deepgram is the one with a large parameter surface (endpointing, utterance-end
timing, keyterms, redaction, smart formatting). None of it is in the adapter:
`provider.options["params"]` is handed to the vendor client as-is, so tuning a
deployment is a row edit. Its server-side endpointing is deliberately not used
as a turn boundary — the engine's VAD and turn controller own that, and two
endpointers is a bug rather than redundancy.

## Language detection

`BaseSttAdapter.detected_language` returns the language the server reported,
normalised to a lowercase code (`"ru"`, `"pt-br"`), or `None`. It feeds the
mid-call language switcher (`src/application/engine/language_switch.py`):
backends that report a language get automatic switching, backends that don't
leave the switcher inert — gated by the `reports_language` capability, never
by a vendor branch.

### Voxtral and language detection

Voxtral the *model* is multilingual and transcribes natively in whatever
language it hears. What is missing is the wire: vLLM's realtime route emits
transcript text deltas and nothing else — no preamble like Qwen3-ASR's
`language Russian<asr_text>`, no metadata field. And unlike Whisper-family
models, whose decoder emits a language token that a server can report for
free, Voxtral's transcription decode is plain text — there is nothing cheap
for the serving layer to harvest. So `detected_language` is honestly `None`,
and calls run in the language they were routed with.

Two workarounds are on the table when an organization on Voxtral needs
mid-call switching (deliberately not implemented yet — recorded here so the
options are not re-derived):

1. **Text-based language ID on the final transcript** — the preferred first
   step. The transcript itself carries the answer, since Voxtral transcribes
   in the spoken language. Run a small LID (fastText `lid.176`, ~1 MB
   quantised, sub-millisecond) over each final in `_emit_final()` and set
   `_detected_language` from it. Gate it per deployment through the model
   row's `capabilities` (e.g. `{"reports_language": true, "text_lid": true}`)
   so it stays operator-togglable data. Known limits: short utterances and
   same-script sibling languages (da/no, cs/sk) — both already absorbed by the
   switcher's `min_utterance_words` guard and confirm-utterances hysteresis.

2. **In-process audio language ID** — the step up if a language pair an
   organization cares about is too close for text LID. A small audio LID model
   (SpeechBrain ECAPA-LID, or Whisper-tiny used only for its language-detect
   head) fed the same VAD-gated utterance audio this adapter already buffers.
   More robust on short or accented speech; costs model weights and inference
   in the worker process. Fits the platform's in-process pattern (Silero,
   Smart Turn) and could become its own integration kind if more than one STT
   backend needs it.

Not worth pursuing: asking the conversation LLM to flag switches (pollutes the
prompt, sits on the critical path) and patching the serving layer (it would
have to run option 1 or 2 server-side anyway — same classifier, other side of
the socket).
