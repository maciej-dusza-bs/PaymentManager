# Payment Manager

Lokalna aplikacja do podsumowania, kategoryzacji i analizy wydatków oraz przychodów. Dane zostają w pliku `data/baza.xlsx`.

## Uruchomienie

```bash
pip install -r requirements.txt
python -m streamlit run app.py
```

Przy pierwszym starcie powstaje baza z domyślnymi kategoriami. Kopia zapasowa trafia do `data/backup/` przed każdym zapisem. Zamknij `baza.xlsx` w Excelu na czas zapisu.
