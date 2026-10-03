"""Layer 3 text features (Track C).

redact.py     Presidio strips personal details -> RedactedText
extract.py    LLM returns each value with the quote that supports it
backfill.py   SetFit trained on LLM labels fills in the 1.5M historical notes
evaluate.py   F1 >= 0.80 (hardship recall >= 0.90) on 300 notes labelled twice
transcribe.py Whisper for voice (first thing we cut)
"""
