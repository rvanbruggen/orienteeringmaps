"""Clubs."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from .. import services
from ..db import get_session

router = APIRouter(prefix="/api/clubs", tags=["clubs"])


def _out(db: Session, club: m.Club) -> s.ClubOut:
    count = db.scalar(select(func.count()).select_from(m.Map).where(m.Map.club_id == club.id)) or 0
    return s.ClubOut(id=club.id, name=club.name, short_name=club.short_name, federation=club.federation,
                     website=club.website, notes=club.notes, map_count=count)


@router.get("", response_model=list[s.ClubOut])
def list_clubs(db: Session = Depends(get_session)):
    return [_out(db, c) for c in db.scalars(select(m.Club).order_by(func.lower(m.Club.name)))]


@router.post("", response_model=s.ClubOut, status_code=201)
def create_club(data: s.ClubIn, db: Session = Depends(get_session)):
    if not data.name:
        raise HTTPException(422, "name is required")
    club = m.Club(**data.model_dump())
    db.add(club)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"A club named {data.name!r} already exists")
    return _out(db, club)


@router.patch("/{club_id}", response_model=s.ClubOut)
def update_club(club_id: int, data: s.ClubIn, db: Session = Depends(get_session)):
    club = services.get_or_404(db, m.Club, club_id)
    vals = data.model_dump(exclude_unset=True)
    if "name" in vals and not vals["name"]:
        raise HTTPException(422, "name cannot be empty")
    for k, v in vals.items():
        setattr(club, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A club with that name already exists")
    return _out(db, club)


@router.delete("/{club_id}", status_code=204)
def delete_club(club_id: int, db: Session = Depends(get_session)):
    """Delete a club. Maps and events that referenced it keep existing without a club."""
    db.delete(services.get_or_404(db, m.Club, club_id))
    db.commit()
