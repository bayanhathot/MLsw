"""Import every model so SQLAlchemy and Alembic see complete metadata."""

from app.database.models.attachment import Attachment
from app.database.models.catalog import CatalogTrack
from app.database.models.external_track import ExternalTrack
from app.database.models.forum import (
    ForumComment,
    ForumCommentVote,
    ForumPost,
    ForumPostVote,
)
from app.database.models.messaging import DirectMessage, Notification
from app.database.models.mix import Mix, MixSegment
from app.database.models.mix_social import MixLike, SavedMix
from app.database.models.music_identity import ListeningEvent, UserMusicProfile
from app.database.models.profile import Profile
from app.database.models.seed_state import ColdSeedRun
from app.database.models.session import (
    DJSession,
    KnownBrokenTrack,
    PromptShortcut,
    SessionFeedback,
    UserPreference,
)
from app.database.models.social import (
    FriendRequest,
    Friendship,
    SocialReport,
    UserBlock,
)
from app.database.models.studio import SavedSegment, StudioBehaviorEvent
from app.database.models.user import User

__all__ = [
    "Attachment",
    "CatalogTrack",
    "ColdSeedRun",
    "DJSession",
    "DirectMessage",
    "ExternalTrack",
    "ForumComment",
    "ForumCommentVote",
    "ForumPost",
    "ForumPostVote",
    "FriendRequest",
    "Friendship",
    "KnownBrokenTrack",
    "ListeningEvent",
    "Mix",
    "MixLike",
    "MixSegment",
    "Notification",
    "Profile",
    "PromptShortcut",
    "SavedMix",
    "SavedSegment",
    "SessionFeedback",
    "SocialReport",
    "StudioBehaviorEvent",
    "User",
    "UserBlock",
    "UserMusicProfile",
    "UserPreference",
]
