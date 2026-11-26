"""Dialog for editing a word's glosses in one gloss language."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
                               QVBoxLayout)

from .. import glosses
from ..store import Store
from .common import MUTED, hebrew_font, stem_label


class GlossDialog(QDialog):
    def __init__(self, store: Store, lex_id: str, gloss_language: str, parent=None):
        super().__init__(parent)
        self.store, self.lex_id, self.language = store, lex_id, gloss_language
        lex = store.lexeme(lex_id)
        self.setWindowTitle(f"Glosses ({gloss_language})")
        self.setMinimumWidth(460)

        word = QLabel(lex["voc_lex_utf8"])
        word.setFont(hebrew_font(24))
        word.setAlignment(Qt.AlignCenter)
        note = QLabel("Separate alternative answers with commas or semicolons. "
                      "Leave a field empty to use the built-in gloss (shown greyed out).")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {MUTED};")

        self.builtin = glosses.builtin_glosses(store, lex_id, gloss_language)
        current = store.glosses(lex_id, gloss_language)
        stems = ["default"] + [s for s, _ in store.stem_counts(lex_id) if s != "NA"]
        self.fields: dict[str, QLineEdit] = {}
        form = QFormLayout()
        for stem in stems:
            edit = QLineEdit()
            own = current.get(stem) if current.get(stem) != self.builtin.get(stem) else None
            edit.setText(own or "")
            edit.setPlaceholderText(self.builtin.get(stem, ""))
            self.fields[stem] = edit
            label = "General" if stem == "default" else stem_label(stem)
            form.addRow(label, edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(word)
        layout.addWidget(note)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def save(self) -> None:
        for stem, edit in self.fields.items():
            text = edit.text().strip()
            if text == self.builtin.get(stem):
                text = ""                       # same as built-in: no own entry needed
            glosses.set_gloss(self.store, self.lex_id, self.language, stem, text)
        self.accept()
