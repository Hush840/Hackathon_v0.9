# Moving the dashboard into the team repo

Everything in this folder is ready to copy. Nothing needs editing first.

Target: https://github.com/wong-yanwen/AGAIF2026_ONE-THIRD-NINE-TO-FIVE_HACKATHON_REPO

---

## The structure it produces

```
AGAIF2026_ONE-THIRD-NINE-TO-FIVE_HACKATHON_REPO/
├── app/                  ← new, yours
│   ├── app.py
│   ├── check_new_data.py
│   ├── requirements.txt
│   └── *.md
├── data/                 ← new, 39 MB
│   ├── Asean.geojson
│   └── jendela_phase2_esg_matrix_*.parquet   (10 countries)
├── data_pipeline/        ← existing, untouched
├── models/               ← existing, untouched
├── utils/                ← existing, untouched
├── main.py
├── requirements.txt      ← existing, broken (see step 5)
└── .gitignore            ← needs two lines added
```

`app.py` resolves its data as `parent.parent / "data"`, so `app/` and `data/` must be
siblings at the repo root. That is why the layout is what it is.

---

## Steps

### 1 · Clone

```
cd "C:\Users\harsh\Downloads\ASEAN Geo AI"
git clone https://github.com/wong-yanwen/AGAIF2026_ONE-THIRD-NINE-TO-FIVE_HACKATHON_REPO.git team-repo
```

### 2 · Copy

Copy the `app` and `data` folders from `_repo_ready` into `team-repo`. Nothing else.

### 3 · Unblock the data in .gitignore

The team `.gitignore` excludes `data/` and `*.parquet`. Your matrices will be silently
skipped without this. Add these three lines **at the very end** of `team-repo\.gitignore`:

```
# Dashboard matrices — small, and the Streamlit app needs them at runtime
!data/
!data/**
```

Order matters. They must come after the existing `data/` and `*.parquet` rules, and
`!data/` has to be present or git will not descend into the folder to see the negation.

### 4 · Commit and push

```
cd team-repo
git add app data .gitignore
git commit -m "Add screening dashboard (app/) and approved matrices (data/)"
git push
```

If `git add` skips the parquets, the negation didn't take. Fall back to:

```
git add -f data
```

Largest single file is Indonesia at 13.6 MB, well inside GitHub's 100 MB limit. Total
39 MB, already slimmed 84% by dropping the `.geo` column the app discards anyway.

### 5 · Streamlit Cloud

Point a **new** app at this repo:

- Repository: `wong-yanwen/AGAIF2026_ONE-THIRD-NINE-TO-FIVE_HACKATHON_REPO`
- Branch: `main`
- **Main file path: `app/app.py`**

Delete the old `hackathonmcmc` app only **after** the new one is confirmed working.

**The root `requirements.txt` will break the build if Streamlit picks it up.** It is a
full `pip freeze` saved as UTF-16, and it pins `pywinpty`, which is Windows-only and
cannot install on Linux. `app/requirements.txt` is a clean five-line file; if the build
fails on dependencies, that root file is why. Yan Wen should regenerate it regardless —
in its current state nobody on macOS or Linux can install from it either.

---

## Two things to tell the team

**The repo is stale relative to the data.** Last commit is 27 August, same SHA as three
weeks ago. The backend that produced the current 66-column export — three governance
tiers, bounded `off_grid_likelihood`, the model circuit breaker — is not in `models/`.
Dhanya should push it, or the repo doesn't reproduce the submission.

**Folder ownership**, so three people in one repo doesn't cost anyone a morning:
Harshana owns `app/` and `data/`, Dhanya owns `models/`, Yan Wen owns `data_pipeline/`.
Shared files — `README.md`, `.gitignore`, root `requirements.txt` — one person at a time,
announced in the group. Everyone pulls before starting and pushes before stopping.

---

## Verified before packaging

- All ten countries load without error
- Streamlit boots clean: HTTP 200, no tracebacks
- Laos boundary renders (the export is named `laos_dr`, which needed adding to the
  boundary lookup — that one-line fix is already in this `app.py`)
- Brunei has 32 tiles, all thin evidence, so it correctly stops with "no
  evidence-qualified candidates". Expected behaviour, but don't open it on stage.
