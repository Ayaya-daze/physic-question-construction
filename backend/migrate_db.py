"""One-shot migration script to update existing SQLite databases with new columns.

Run: python migrate_db.py   (from the backend/ directory, or set DB path)

This does:
1. Add new columns to knowledge_points if they don't exist
2. Clear old high-school knowledge points (source='seed' or predefined)
3. Clear old questions that reference now-deleted knowledge points

Safe to run repeatedly — it checks if columns exist before adding.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Default DB path — adjust if needed
DB_PATH = Path(__file__).resolve().parent / "physics_questions.db"

if not DB_PATH.exists():
    print(f"Database not found at {DB_PATH}. Nothing to migrate.")
    sys.exit(0)

conn = sqlite3.connect(str(DB_PATH))
conn.execute("PRAGMA foreign_keys=ON")
cursor = conn.cursor()

# 1. Add new columns to knowledge_points (ignore errors if already present)
_kp_new_cols = [
    ("canonical_name", "VARCHAR(200)"),
    ("definition", "TEXT"),
    ("source", "VARCHAR(20) DEFAULT 'human'"),
    ("confidence", "FLOAT DEFAULT 1.0"),
    ("status", "VARCHAR(20) DEFAULT 'approved'"),
    ("created_from_question_id", "INTEGER REFERENCES questions(id) ON DELETE SET NULL"),
]

existing = {row[1] for row in cursor.execute("PRAGMA table_info(knowledge_points)")}
for col_name, col_type in _kp_new_cols:
    if col_name not in existing:
        try:
            cursor.execute(f"ALTER TABLE knowledge_points ADD COLUMN {col_name} {col_type}")
            print(f"  + Added column knowledge_points.{col_name}")
        except sqlite3.OperationalError as e:
            print(f"  ! Could not add knowledge_points.{col_name}: {e}")

# 2. Set defaults for existing knowledge points where source is still NULL/empty
#    (does NOT delete any data — only fills in missing column defaults)
cursor.execute(
    "UPDATE knowledge_points SET source='human', status='approved', confidence=1.0 "
    "WHERE source IS NULL OR source=''"
)
updated_kps = cursor.rowcount
print(f"  Set defaults on {updated_kps} existing knowledge points")

# 3. Verify current state
cursor.execute("SELECT COUNT(*) FROM knowledge_points")
kp_count = cursor.fetchone()[0]
cursor.execute("SELECT source, COUNT(*) FROM knowledge_points GROUP BY source")
source_counts = cursor.fetchall()
print(f"  Knowledge points by source: {dict(source_counts)}")
cursor.execute("SELECT COUNT(*) FROM questions")
question_count = cursor.fetchone()[0]
print(f"  {question_count} questions in database")

# 4. Verify final state
cursor.execute("SELECT COUNT(*) FROM knowledge_points")
kp_count = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM knowledge_point_candidates")
kpc_count = cursor.fetchone()[0]
print(f"\nFinal state: {kp_count} knowledge_points, {kpc_count} knowledge_point_candidates")

# 6. Add core columns to paper_export_artifacts (if table exists but missing these)
_export_core_cols = [
    ("latex_engine", "VARCHAR(20) DEFAULT 'xelatex'"),
    ("format", "VARCHAR(20) DEFAULT 'tex_pdf'"),
    ("variant", "VARCHAR(50) DEFAULT 'paper_with_answers'"),
    ("template_id", "VARCHAR(50) DEFAULT 'default_general_physics'"),
]

# 7. Add new question/answer split columns to paper_export_artifacts
_export_split_cols = [
    ("questions_tex_path", "VARCHAR(1000)"),
    ("questions_pdf_path", "VARCHAR(1000)"),
    ("questions_build_log", "TEXT"),
    ("answers_tex_path", "VARCHAR(1000)"),
    ("answers_pdf_path", "VARCHAR(1000)"),
    ("answers_build_log", "TEXT"),
]

# Check if paper_export_artifacts table exists
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='paper_export_artifacts'")
if cursor.fetchone():
    existing_export = {row[1] for row in cursor.execute("PRAGMA table_info(paper_export_artifacts)")}
    for col_name, col_type in _export_core_cols + _export_split_cols:
        if col_name not in existing_export:
            try:
                cursor.execute(f"ALTER TABLE paper_export_artifacts ADD COLUMN {col_name} {col_type}")
                print(f"  + Added column paper_export_artifacts.{col_name}")
            except sqlite3.OperationalError as e:
                print(f"  ! Could not add paper_export_artifacts.{col_name}: {e}")
else:
    print("  (paper_export_artifacts table does not exist yet — will be created by SQLAlchemy)")

conn.commit()
conn.close()
print("Migration complete.")
