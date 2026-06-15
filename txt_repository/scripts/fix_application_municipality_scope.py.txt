#!/usr/bin/env python
"""Audit and optionally fix municipality/program ownership mismatches in applications.

Why this exists:
- Legacy migrations can leave applications linked to programs now owned by a different municipality.
- Admin application pages are municipality-scoped by applicant profile, but data may still be inconsistent.

What this script does:
1. Detect applications where applicant municipality != current program owner municipality.
2. Try to find an equivalent program in the applicant municipality using exact
   normalized (program_name, program_type) matching.
3. In dry-run mode (default), print a report only.
4. In apply mode, relink only when exactly one safe candidate is found.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func
from sqlalchemy.orm import aliased

from app import create_app
from app.extensions import db
from app.models import AdminUsers, Applications, CommunityUsers, Programs, User


@dataclass
class MismatchRow:
    application_id: int
    user_id: int
    applicant_municipality: str
    current_program_id: int
    current_program_name: str
    current_program_type: str
    owner_municipality: Optional[str]


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _collect_mismatches(limit: Optional[int] = None) -> List[MismatchRow]:
    owner_user = aliased(User)
    owner_admin = aliased(AdminUsers)

    query = (
        db.session.query(
            Applications.id.label("application_id"),
            Applications.user_id.label("user_id"),
            CommunityUsers.municipality.label("applicant_municipality"),
            Programs.id.label("program_id"),
            Programs.program_name.label("program_name"),
            Programs.program_type.label("program_type"),
            owner_admin.municipality.label("owner_municipality"),
        )
        .join(CommunityUsers, Applications.user_id == CommunityUsers.user_id)
        .join(Programs, Applications.program_id == Programs.id)
        .join(owner_user, Programs.user_id == owner_user.id)
        .outerjoin(owner_admin, owner_admin.user_id == owner_user.id)
        .order_by(Applications.id.asc())
    )

    if limit and limit > 0:
        query = query.limit(limit)

    mismatches: List[MismatchRow] = []
    for row in query.all():
        applicant_muni = _norm(row.applicant_municipality)
        owner_muni = _norm(row.owner_municipality)

        if not applicant_muni:
            continue

        if applicant_muni != owner_muni:
            mismatches.append(
                MismatchRow(
                    application_id=int(row.application_id),
                    user_id=int(row.user_id),
                    applicant_municipality=row.applicant_municipality or "",
                    current_program_id=int(row.program_id),
                    current_program_name=row.program_name or "",
                    current_program_type=row.program_type or "",
                    owner_municipality=row.owner_municipality,
                )
            )

    return mismatches


def _find_relink_candidates(program_name: str, program_type: str, target_municipality: str) -> List[int]:
    owner_user = aliased(User)

    normalized_name = _norm(program_name)
    normalized_type = _norm(program_type)
    normalized_target_muni = _norm(target_municipality)

    if not normalized_name or not normalized_target_muni:
        return []

    rows = (
        db.session.query(Programs.id)
        .join(owner_user, Programs.user_id == owner_user.id)
        .join(AdminUsers, AdminUsers.user_id == owner_user.id)
        .filter(
            owner_user.role == "admin",
            func.lower(func.trim(AdminUsers.municipality)) == normalized_target_muni,
            func.lower(func.trim(Programs.program_name)) == normalized_name,
            func.coalesce(func.lower(func.trim(Programs.program_type)), "") == normalized_type,
        )
        .all()
    )

    return [int(row.id) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit/fix legacy municipality-program application mismatches")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply safe relinks (exactly one candidate match only)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit scanned rows for quick checks (0 means no limit)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-row diagnostics",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        mismatches = _collect_mismatches(limit=args.limit if args.limit > 0 else None)
        print(f"Found {len(mismatches)} mismatch application(s).")

        if not mismatches:
            return

        relinkable = 0
        ambiguous = 0
        missing = 0
        updated = 0

        for item in mismatches:
            candidates = _find_relink_candidates(
                program_name=item.current_program_name,
                program_type=item.current_program_type,
                target_municipality=item.applicant_municipality,
            )

            if len(candidates) == 1:
                relinkable += 1
                candidate_program_id = candidates[0]
                if args.verbose:
                    print(
                        "RELINKABLE "
                        f"app={item.application_id} user={item.user_id} "
                        f"program={item.current_program_id} -> {candidate_program_id} "
                        f"applicant_muni='{item.applicant_municipality}' owner_muni='{item.owner_municipality or ''}'"
                    )

                if args.apply and candidate_program_id != item.current_program_id:
                    application = Applications.query.get(item.application_id)
                    if not application:
                        continue
                    application.program_id = candidate_program_id
                    application.updated_at = datetime.utcnow()
                    updated += 1
            elif len(candidates) > 1:
                ambiguous += 1
                if args.verbose:
                    print(
                        "AMBIGUOUS "
                        f"app={item.application_id} user={item.user_id} candidates={candidates} "
                        f"applicant_muni='{item.applicant_municipality}'"
                    )
            else:
                missing += 1
                if args.verbose:
                    print(
                        "NO_MATCH "
                        f"app={item.application_id} user={item.user_id} "
                        f"program_name='{item.current_program_name}' program_type='{item.current_program_type}' "
                        f"applicant_muni='{item.applicant_municipality}'"
                    )

        print(f"Relinkable (safe single-match): {relinkable}")
        print(f"Ambiguous (multiple candidates): {ambiguous}")
        print(f"Missing (no candidate): {missing}")

        if args.apply:
            db.session.commit()
            print(f"Applied updates: {updated}")
        else:
            db.session.rollback()
            print("Dry-run only. No database changes were committed.")


if __name__ == "__main__":
    main()
