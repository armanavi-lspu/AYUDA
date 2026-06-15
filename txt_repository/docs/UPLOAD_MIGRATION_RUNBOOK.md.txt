# Upload Migration Runbook (Static -> Private)

This runbook migrates uploads from static/uploads to the private upload root at /var/lib/ayuda/uploads, and normalizes database paths so stored file paths are relative to the private root.

## Scope

The migration script updates these models/fields:
- User.profile_pic
- CommunityUsers.(senior_citizen_document_path, pwd_document_path, solo_parent_document_path)
- ShelterPhotos.photo_path
- CALDocuments.file_path
- AnnouncementImages.image_path
- FileAttachment.file_path
- AssessmentDocument.file_path
- ApplicationDocumentUploads.file_path

## Preconditions

- Deploy the code that uses UPLOAD_ROOT and /files routes.
- Ensure UPLOAD_ROOT is set on the server (recommended: /var/lib/ayuda/uploads).
- Ensure the service account can read/write the new upload directory.

Example .env entry:
```
UPLOAD_ROOT=/var/lib/ayuda/uploads
```

## Step-by-step (Production)

1. Stop the service
```
sudo systemctl stop ayuda
```

2. Backup database
```
pg_dump "$DATABASE_URL" > /var/backups/ayuda_db_$(date +%Y%m%d_%H%M%S).sql
```

3. Backup old uploads
```
sudo tar -czf /var/backups/ayuda_uploads_$(date +%Y%m%d_%H%M%S).tgz /var/www/ayuda/static/uploads
```

4. Ensure destination exists
```
sudo mkdir -p /var/lib/ayuda/uploads
sudo chown -R www-data:www-data /var/lib/ayuda/uploads
```

5. Dry run the migration script
```
source /var/www/ayuda/.venv/bin/activate
cd /var/www/ayuda
python scripts/migrate_uploads_to_private.py --dry-run
```

6. Run the migration (moves files and updates DB)
```
python scripts/migrate_uploads_to_private.py
```

7. Optional: move any leftover static uploads (orphans)
```
sudo rsync -a --ignore-existing /var/www/ayuda/static/uploads/ /var/lib/ayuda/uploads/
```

8. Restart the service
```
sudo systemctl start ayuda
```

9. Validate
- Log in as admin and community users.
- Open profile pictures, announcements, shelter photos, CA documents, and program attachments.
- Check for 404s in the browser and in /var/log/ayuda/error.log.

## Rollback

1. Stop the service
```
sudo systemctl stop ayuda
```

2. Restore uploads backup
```
sudo rm -rf /var/lib/ayuda/uploads
sudo tar -xzf /var/backups/ayuda_uploads_<timestamp>.tgz -C /
```

3. Restore database backup
```
psql "$DATABASE_URL" < /var/backups/ayuda_db_<timestamp>.sql
```

4. Restart the service
```
sudo systemctl start ayuda
```

## Notes

- The migration script uses the configured UPLOAD_ROOT and the static/uploads folder as the old source.
- Use --db-only if files are already moved, or --files-only if DB paths are already normalized.
- Keep backups until you confirm all protected /files routes work correctly.
