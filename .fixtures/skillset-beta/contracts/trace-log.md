# Trace Log Protocol

A trace log is a plain-text stream, one event per line, pipe-separated:

    LEVEL|stage|message

- LEVEL is one of TRC, WRN, ERR.
- stage is a lowercase token naming the pipeline stage.
- message is free text without pipes.
- The final line of a run is always `TRC|end|done`.
