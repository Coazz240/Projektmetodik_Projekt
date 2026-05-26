<<<<<<< HEAD
from __future__ import annotations

from .db import engine
from .models import Base


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("✅ Databastabeller skapade (om de inte fanns).")


if __name__ == "__main__":
=======
from __future__ import annotations

from .db import engine
from .models import Base


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("✅ Databastabeller skapade (om de inte fanns).")


if __name__ == "__main__":
>>>>>>> 147d6e3 (Ändringar i main.py för get /ui/reports/weekly , la till templates/weekly.html)
    main()