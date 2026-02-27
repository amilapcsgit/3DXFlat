from __future__ import annotations

from typing import Dict, Iterable, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ui.theme import tokens


def _edge_key(edge: Sequence[int]) -> Tuple[int, int]:
    a = int(edge[0])
    b = int(edge[1])
    return (a, b) if a < b else (b, a)


class FlattenPanelWidget(QWidget):
    requestSetAnchor = Signal()
    requestToggleCut = Signal()
    requestRemoveCut = Signal(object)
    requestClearCuts = Signal()
    requestAutoGuessAnchor = Signal()
    precisionChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FlattenPanel")
        self.setMinimumWidth(286)
        self.setMaximumWidth(360)

        root = QVBoxLayout(self)
        root.setContentsMargins(tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S)
        root.setSpacing(tokens.SPACE_S)

        title = QLabel("Appiattito", self)
        title.setObjectName("PanelTitle")
        root.addWidget(title)

        self.group_selection = QGroupBox("Selezioni", self)
        sel_layout = QVBoxLayout(self.group_selection)
        sel_layout.setContentsMargins(tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S)
        self.faces_count_label = QLabel("Facce selezionate: 0", self.group_selection)
        self.faces_count_label.setObjectName("FieldLabel")
        sel_layout.addWidget(self.faces_count_label)
        root.addWidget(self.group_selection)

        self.group_anchor = QGroupBox("Bordo (Anchor)", self)
        anchor_layout = QVBoxLayout(self.group_anchor)
        anchor_layout.setContentsMargins(tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S)
        self.anchor_field = QLineEdit(self.group_anchor)
        self.anchor_field.setReadOnly(True)
        self.anchor_field.setObjectName("Field")
        self.anchor_field.setText("None")
        anchor_layout.addWidget(self.anchor_field)

        anchor_btn_row = QHBoxLayout()
        self.btn_set_anchor = QPushButton("Imposta Bordo", self.group_anchor)
        self.btn_set_anchor.setObjectName("StandardButton")
        self.btn_auto_anchor = QPushButton("Auto Bordo", self.group_anchor)
        self.btn_auto_anchor.setObjectName("StandardButton")
        anchor_btn_row.addWidget(self.btn_set_anchor)
        anchor_btn_row.addWidget(self.btn_auto_anchor)
        anchor_layout.addLayout(anchor_btn_row)
        root.addWidget(self.group_anchor)

        self.group_cuts = QGroupBox("Tagli di scarico (Relief cuts)", self)
        cuts_layout = QVBoxLayout(self.group_cuts)
        cuts_layout.setContentsMargins(tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S)
        self.cut_edges_list = QListWidget(self.group_cuts)
        self.cut_edges_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.cut_edges_list.setMinimumHeight(120)
        cuts_layout.addWidget(self.cut_edges_list)

        cuts_btn_row = QHBoxLayout()
        self.btn_toggle_cut = QPushButton("Aggiungi/Rimuovi", self.group_cuts)
        self.btn_toggle_cut.setObjectName("StandardButton")
        self.btn_remove_selected = QPushButton("Rimuovi selezionato", self.group_cuts)
        self.btn_remove_selected.setObjectName("StandardButton")
        self.btn_clear_cuts = QPushButton("Pulisci", self.group_cuts)
        self.btn_clear_cuts.setObjectName("StandardButton")
        cuts_btn_row.addWidget(self.btn_toggle_cut)
        cuts_btn_row.addWidget(self.btn_remove_selected)
        cuts_btn_row.addWidget(self.btn_clear_cuts)
        cuts_layout.addLayout(cuts_btn_row)
        root.addWidget(self.group_cuts)

        self.group_precision = QGroupBox("Precisione", self)
        precision_layout = QVBoxLayout(self.group_precision)
        precision_layout.setContentsMargins(tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S)
        self.precision_label = QLabel("Precisione: 12", self.group_precision)
        self.precision_label.setObjectName("FieldLabel")
        self.precision_slider = QSlider(Qt.Orientation.Horizontal, self.group_precision)
        self.precision_slider.setRange(0, 200)
        self.precision_slider.setValue(12)
        precision_layout.addWidget(self.precision_label)
        precision_layout.addWidget(self.precision_slider)
        root.addWidget(self.group_precision)

        self.group_status = QGroupBox("Stato", self)
        status_layout = QVBoxLayout(self.group_status)
        status_layout.setContentsMargins(tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S, tokens.SPACE_S)
        self.status_line = QLabel("Seam: A[none]  C[0]  Patch: -", self.group_status)
        self.status_line.setWordWrap(True)
        self.status_line.setObjectName("FieldLabel")
        self.guidance_line = QLabel(
            "Cut/Seam mode: passa vicino al bordo per evidenziare.\n"
            "Click = taglio di scarico.\n"
            "Shift+Click = bordo anchor.",
            self.group_status,
        )
        self.guidance_line.setWordWrap(True)
        self.guidance_line.setObjectName("FieldLabel")
        self.guidance_line.setStyleSheet(f"color:{tokens.TEXT_SECONDARY};")
        status_layout.addWidget(self.status_line)
        status_layout.addWidget(self._make_separator())
        status_layout.addWidget(self.guidance_line)
        root.addWidget(self.group_status)
        root.addStretch(1)

        self.btn_set_anchor.clicked.connect(self.requestSetAnchor.emit)
        self.btn_toggle_cut.clicked.connect(self.requestToggleCut.emit)
        self.btn_clear_cuts.clicked.connect(self.requestClearCuts.emit)
        self.btn_auto_anchor.clicked.connect(self.requestAutoGuessAnchor.emit)
        self.btn_remove_selected.clicked.connect(self._emit_remove_selected)
        self.precision_slider.valueChanged.connect(self._on_precision_changed)

    def _make_separator(self) -> QWidget:
        sep = QFrame(self.group_status)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setLineWidth(1)
        return sep

    def _emit_remove_selected(self) -> None:
        edge = self.selected_cut_edge()
        if edge is None:
            return
        self.requestRemoveCut.emit(edge)

    def _on_precision_changed(self, value: int) -> None:
        self.precision_label.setText(f"Precisione: {int(value)}")
        self.precisionChanged.emit(int(value))

    def set_precision_value(self, value: int) -> None:
        ivalue = int(value)
        self.precision_slider.blockSignals(True)
        self.precision_slider.setValue(ivalue)
        self.precision_slider.blockSignals(False)
        self.precision_label.setText(f"Precisione: {ivalue}")

    def set_faces_count(self, count: int) -> None:
        self.faces_count_label.setText(f"Facce selezionate: {int(count)}")

    def set_anchor_edge(self, edge: Sequence[int] | None, label: str | None = None) -> None:
        if edge is None:
            self.anchor_field.setText("None")
            return
        if label:
            self.anchor_field.setText(str(label))
            return
        a, b = _edge_key(edge)
        self.anchor_field.setText(f"Edge: v{a}-v{b}")

    def set_cut_edges(
        self,
        edges: Iterable[Sequence[int]],
        *,
        labels: Dict[Tuple[int, int], str] | None = None,
    ) -> None:
        current = self.selected_cut_edge()
        self.cut_edges_list.clear()
        labels = labels or {}
        normalized = sorted({_edge_key(e) for e in edges})
        for edge in normalized:
            text = labels.get(edge) or f"Edge: v{edge[0]}-v{edge[1]}"
            item = QListWidgetItem(text, self.cut_edges_list)
            item.setData(Qt.ItemDataRole.UserRole, (int(edge[0]), int(edge[1])))
            self.cut_edges_list.addItem(item)
            if current is not None and tuple(current) == edge:
                item.setSelected(True)

    def selected_cut_edge(self) -> Tuple[int, int] | None:
        item = self.cut_edges_list.currentItem()
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or len(data) != 2:
            return None
        return _edge_key(data)

    def set_status_line(self, text: str) -> None:
        self.status_line.setText(str(text))

    def set_guidance_text(self, text: str) -> None:
        self.guidance_line.setText(str(text))
