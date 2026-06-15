#!/usr/bin/env python
"""Migrate uploads to private UPLOAD_ROOT and normalize DB paths.

This script:
- Normalizes stored file paths by removing static/ and uploads/ prefixes.
- Moves files from static/uploads into UPLOAD_ROOT while preserving relative paths.
- Updates database fields to store relative paths.

Usage examples:
  python scripts/migrate_uploads_to_private.py --dry-run
  python scripts/migrate_uploads_to_private.py
  python scripts/migrate_uploads_to_private.py --db-only
  python scripts/migrate_uploads_to_private.py --files-only
"""
import argparse
import os
import shutil

from app import create_app
from app.extensions import db
from app.models import (
    User,
    CommunityUsers,
    ShelterPhotos,
    CALDocuments,
    AnnouncementImages,
    FileAttachment,
    AssessmentDocument,
    ApplicationDocumentUploads,
)
from app.utils import get_upload_root


def _normalize_relative_path(raw_path):
    if not raw_path:
        return None
    normalized = str(raw_path).replace('\\', '/').strip()
    if not normalized:
        return None
    normalized = normalized.lstrip('/')

    if normalized.startswith('static/'):
        normalized = normalized[len('static/'):]

    if normalized.startswith('uploads/'):
        normalized = normalized[len('uploads/'):]

    return normalized or None


def _rel_from_absolute(abs_path, old_root, new_root):
    if not abs_path:
        return None
    abs_path = os.path.normpath(abs_path)
    if old_root and abs_path.startswith(old_root):
        return os.path.relpath(abs_path, old_root).replace('\\', '/')
    if new_root and abs_path.startswith(new_root):
        return os.path.relpath(abs_path, new_root).replace('\\', '/')
    return None


def _find_existing_source(raw_path, normalized_rel, old_upload_root, new_upload_root):
    candidates = []
    raw_str = str(raw_path or '').replace('\\', '/').strip()

    if raw_str and os.path.isabs(raw_str):
        candidates.append(os.path.normpath(raw_str))

    if normalized_rel:
        candidates.append(os.path.normpath(os.path.join(old_upload_root, normalized_rel)))
        candidates.append(os.path.normpath(os.path.join(new_upload_root, normalized_rel)))

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def _move_file(source_path, dest_path, dry_run):
    if not source_path or not dest_path:
        return 'missing'

    source_path = os.path.normpath(source_path)
    dest_path = os.path.normpath(dest_path)

    if source_path == dest_path:
        return 'already'

    if not os.path.exists(source_path):
        return 'missing'

    if os.path.exists(dest_path):
        return 'collision'

    if not dry_run:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.move(source_path, dest_path)

    return 'moved'


def _process_field(record, field_name, old_upload_root, new_upload_root, options, stats, missing):
    raw_value = getattr(record, field_name)
    if not raw_value:
        stats['empty'] += 1
        return

    raw_str = str(raw_value).replace('\\', '/').strip()
    abs_path = raw_str if os.path.isabs(raw_str) else None
    normalized_rel = _normalize_relative_path(raw_str)

    if abs_path:
        rel_from_abs = _rel_from_absolute(abs_path, old_upload_root, new_upload_root)
        if rel_from_abs:
            normalized_rel = rel_from_abs
        else:
            stats['external'] += 1

    if not normalized_rel:
        stats['unresolved'] += 1
        return

    source_path = _find_existing_source(raw_str, normalized_rel, old_upload_root, new_upload_root)
    dest_path = os.path.join(new_upload_root, normalized_rel)

    if not options.db_only:
        move_result = _move_file(source_path, dest_path, options.dry_run)
        stats[move_result] += 1
        if move_result == 'missing':
            missing.append((field_name, getattr(record, 'id', None), raw_str))

    if not options.files_only:
        if raw_str != normalized_rel:
            stats['updated'] += 1
            if not options.dry_run:
                setattr(record, field_name, normalized_rel)


def _apply_records(model, field_names, old_upload_root, new_upload_root, options, totals, missing):
    stats = {
        'empty': 0,
        'external': 0,
        'unresolved': 0,
        'moved': 0,
        'already': 0,
        'collision': 0,
        'missing': 0,
        'updated': 0,
    }

    records = model.query.all()
    for record in records:
        for field_name in field_names:
            _process_field(record, field_name, old_upload_root, new_upload_root, options, stats, missing)

    totals['models'].append((model.__name__, stats, len(records)))
    for key, value in stats.items():
        totals[key] = totals.get(key, 0) + value


def _print_summary(totals, missing):
    print("\n=== Upload Migration Summary ===")
    print(f"Updated DB fields: {totals.get('updated', 0)}")
    print(f"Files moved: {totals.get('moved', 0)}")
    print(f"Already in destination: {totals.get('already', 0)}")
    print(f"Missing files: {totals.get('missing', 0)}")
    print(f"Collisions: {totals.get('collision', 0)}")
    print(f"External/absolute paths skipped: {totals.get('external', 0)}")
    print(f"Unresolved paths: {totals.get('unresolved', 0)}")
    print(f"Empty paths: {totals.get('empty', 0)}")

    if missing:
        print("\nMissing file samples:")
        for entry in missing[:20]:
            field_name, record_id, raw_path = entry
            print(f"- {field_name} id={record_id} path={raw_path}")
        if len(missing) > 20:
            print(f"...and {len(missing) - 20} more")

    print("\nPer-model breakdown:")
    for model_name, stats, record_count in totals.get('models', []):
        print(
            f"- {model_name}: records={record_count}, "
            f"updated={stats['updated']}, moved={stats['moved']}, "
            f"missing={stats['missing']}, collisions={stats['collision']}"
        )


def main():
    parser = argparse.ArgumentParser(description='Migrate uploads to private UPLOAD_ROOT')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without writing')
    parser.add_argument('--db-only', action='store_true', help='Update DB paths only, do not move files')
    parser.add_argument('--files-only', action='store_true', help='Move files only, do not update DB paths')
    args = parser.parse_args()

    app = create_app()

    with app.app_context():
        old_upload_root = os.path.normpath(os.path.join(app.static_folder, 'uploads'))
        new_upload_root = os.path.normpath(get_upload_root())

        print("=== Upload Migration ===")
        print(f"Old upload root: {old_upload_root}")
        print(f"New upload root: {new_upload_root}")
        print(f"Dry run: {args.dry_run}")
        print(f"DB only: {args.db_only}")
        print(f"Files only: {args.files_only}\n")

        totals = {'models': []}
        missing = []

        _apply_records(User, ['profile_pic'], old_upload_root, new_upload_root, args, totals, missing)
        _apply_records(
            CommunityUsers,
            [
                'senior_citizen_document_path',
                'pwd_document_path',
                'solo_parent_document_path',
            ],
            old_upload_root,
            new_upload_root,
            args,
            totals,
            missing,
        )
        _apply_records(ShelterPhotos, ['photo_path'], old_upload_root, new_upload_root, args, totals, missing)
        _apply_records(CALDocuments, ['file_path'], old_upload_root, new_upload_root, args, totals, missing)
        _apply_records(AnnouncementImages, ['image_path'], old_upload_root, new_upload_root, args, totals, missing)
        _apply_records(FileAttachment, ['file_path'], old_upload_root, new_upload_root, args, totals, missing)
        _apply_records(AssessmentDocument, ['file_path'], old_upload_root, new_upload_root, args, totals, missing)
        _apply_records(ApplicationDocumentUploads, ['file_path'], old_upload_root, new_upload_root, args, totals, missing)

        if not args.files_only:
            if args.dry_run:
                db.session.rollback()
            else:
                db.session.commit()

        _print_summary(totals, missing)


if __name__ == '__main__':
    main()
