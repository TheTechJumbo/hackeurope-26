# sample_requests

This folder stores one JSON file per generated LLM request/response.

Each file has the following top-level keys:
- `id`, `timestamp`, `template_key`, `template`, `filled_prompt`, `placeholders`, `request_payload`, `response`, `children`

`children` is an array so you can nest related follow-up requests (tree-style).
