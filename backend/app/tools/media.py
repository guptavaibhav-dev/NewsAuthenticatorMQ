"""Media provenance is not wired into Layer 1.

Intended later design (not implemented):

- C2PA / Content Credentials: if an image or video carries a signed manifest,
  record issuer, signing time, and whether the manifest validates. A valid
  credential is provenance, not proof that the depicted event is true. A
  missing credential is a coverage gap, never a signal of falsity.
- Reverse image / video search: find earlier or alternative appearances of
  the same media. Earlier appearances can inform reuse and context; they do
  not by themselves classify the story as authentic or inauthentic.

``inspect_media`` is intentionally absent. Layer 1 must not emit a media
trace entry or InputPayload field until this work is implemented.
"""
