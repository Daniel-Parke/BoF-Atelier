"""Read-only, spoiler-aware controls over the identified game's original tables."""

from tools import progression


class Rulebook:
    def __init__(self, tables: dict):
        self.tables = tables
        self.reveal = False
        self.genes: list[int] = []
        self.first = 0
        self.second = 1

    def _name(self, names, index, category):
        return names[index] if self.reveal else f"{category} {index:02d}"

    def model(self) -> dict:
        controls = []
        details = {}
        if self.tables["game"] == "bof3":
            for i in range(len(progression.GENES)):
                controls.append(
                    {
                        "id": i,
                        "label": self._name(progression.GENES, i, "Gene"),
                        "ap": self.tables["costs"][i],
                        "selected": i in self.genes,
                    }
                )
            summary = "Choose up to three genes to inspect their original cost and special recipe rule."
            if self.genes:
                result = progression.gene_selection(self.tables, self.genes)
                summary = (
                    f"Initial AP {result['initial_ap']}. {result['interpretation']}"
                )
        else:
            for a, label in enumerate(
                (
                    "Previous first master",
                    "Next first master",
                    "Previous second master",
                    "Next second master",
                )
            ):
                controls.append({"id": a, "label": label, "selected": False})
            a = self._name(progression.MASTERS, self.first, "Master")
            b = self._name(progression.MASTERS, self.second, "Master")
            comparison = progression.master_comparison(self.tables, self.first, self.second)
            change = comparison["second_minus_first"]
            details = {
                "first": a, "second": b,
                "masters": [self._name(progression.MASTERS, i, "Master") for i in range(len(progression.MASTERS))],
                "stats": [{"label": stat if stat in ("HP", "AP") else stat.capitalize(),
                           "first": comparison["first_modifier"][stat],
                           "second": comparison["second_modifier"][stat], "difference": delta}
                          for stat, delta in change.items()],
            }
            summary = (
                f"{a} → {b}. Change per level: "
                + ", ".join(f"{key} {value:+d}" for key, value in change.items())
                + "."
            )
        return {"controls": controls, "summary": summary, "reveal": self.reveal, **details}

    def apply(self, value):
        if value == "names":
            self.reveal = not self.reveal
        elif (
            self.tables["game"] == "bof3"
            and type(value) is int
            and 0 <= value < len(progression.GENES)
        ):
            if value in self.genes:
                self.genes.remove(value)
            elif len(self.genes) < 3:
                self.genes.append(value)
            else:
                raise ValueError("Remove one of the three selected genes first.")
        elif self.tables["game"] == "bof4" and type(value) is int and value in range(4):
            step = 1 if value % 2 else -1
            if value < 2:
                self.first = (self.first + step) % len(progression.MASTERS)
            else:
                self.second = (self.second + step) % len(progression.MASTERS)
        elif self.tables["game"] == "bof4" and isinstance(value, dict):
            field, index = value.get("compare"), value.get("id")
            if field not in ("first", "second") or type(index) is not int or not 0 <= index < len(progression.MASTERS):
                raise ValueError("Choose a valid master for the comparison.")
            setattr(self, field, index)
        else:
            raise ValueError("Choose an available rulebook action.")
