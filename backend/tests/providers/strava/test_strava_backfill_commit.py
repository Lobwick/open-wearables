"""A Strava backfill must keep the samples it fetches, whether or not the workouts are already known.

`EventRecordRepository.create` rolls the session back when a workout already exists, and the
sync task closes its session without a final commit. Samples that were inserted but not yet
committed were therefore discarded: a re-sync of known workouts downloaded every stream and
stored none of them.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models import DataPointSeries, DataSource, EventRecord
from app.repositories.event_record_repository import EventRecordRepository
from app.repositories.user_connection_repository import UserConnectionRepository
from app.schemas.providers.strava import ActivityJSON as StravaActivityJSON
from app.services.providers.strava.oauth import StravaOAuth
from app.services.providers.strava.workouts import StravaWorkouts
from tests.factories import UserFactory

_SETTINGS = "app.services.providers.strava.workouts.settings"


def _activity(strava_id: int, start_date: str) -> StravaActivityJSON:
    return StravaActivityJSON(
        id=strava_id,
        name=f"Ride {strava_id}",
        type="Ride",
        sport_type="Ride",
        start_date=start_date,
        elapsed_time=3600,
        utc_offset=3600.0,
        device_name="Garmin Edge 850",
    )


def _streams(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    return {"time": {"data": [0, 1, 2]}, "heartrate": {"data": [120, 121, 122]}, "watts": {"data": [200, 210, 220]}}


@pytest.fixture
def strava_workouts() -> StravaWorkouts:
    connection_repo = UserConnectionRepository()
    oauth = StravaOAuth(
        user_repo=MagicMock(),
        connection_repo=connection_repo,
        provider_name="strava",
        api_base_url="https://www.strava.com",
    )
    return StravaWorkouts(
        workout_repo=EventRecordRepository(EventRecord),
        connection_repo=connection_repo,
        provider_name="strava",
        api_base_url="https://www.strava.com",
        oauth=oauth,
    )


@pytest.fixture
def activities() -> list[StravaActivityJSON]:
    return [_activity(101, "2024-01-15T08:00:00Z"), _activity(102, "2024-01-16T08:00:00Z")]


def _stored_samples(db: Session, user_id: Any) -> int:
    return (
        db.query(DataPointSeries)
        .join(DataSource, DataPointSeries.data_source_id == DataSource.id)
        .filter(DataSource.user_id == user_id)
        .count()
    )


def _backfill(strava_workouts: StravaWorkouts, db: Session, user_id: Any, activities: list, *, samples: bool) -> int:
    with (
        patch(_SETTINGS, ingest_workout_samples=samples),
        patch.object(strava_workouts, "get_workouts", return_value=activities),
        patch.object(strava_workouts, "_make_api_request", side_effect=_streams),
    ):
        return strava_workouts.load_data(db, user_id)


class TestBackfillKeepsSamples:
    def test_samples_of_workouts_already_imported_are_kept(
        self, strava_workouts: StravaWorkouts, db: Session, activities: list[StravaActivityJSON]
    ) -> None:
        user = UserFactory()
        # The workouts were imported before sample ingestion was switched on.
        _backfill(strava_workouts, db, user.id, activities, samples=False)
        assert _stored_samples(db, user.id) == 0

        _backfill(strava_workouts, db, user.id, activities, samples=True)
        db.rollback()  # what closing the sync task's session does with anything uncommitted

        # 2 activities x (3 heart rate + 3 power) samples
        assert _stored_samples(db, user.id) == 12

    def test_samples_of_the_last_new_workout_are_kept(
        self, strava_workouts: StravaWorkouts, db: Session, activities: list[StravaActivityJSON]
    ) -> None:
        user = UserFactory()

        _backfill(strava_workouts, db, user.id, activities, samples=True)
        db.rollback()

        assert _stored_samples(db, user.id) == 12

    def test_nothing_is_stored_with_the_flag_off(
        self, strava_workouts: StravaWorkouts, db: Session, activities: list[StravaActivityJSON]
    ) -> None:
        user = UserFactory()

        _backfill(strava_workouts, db, user.id, activities, samples=False)
        db.rollback()

        assert _stored_samples(db, user.id) == 0
