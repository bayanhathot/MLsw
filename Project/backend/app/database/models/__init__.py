"""Import every model so SQLAlchemy and Alembic see complete metadata."""

from app.database.models.attachment import Attachment
from app.database.models.forum import ForumComment, ForumCommentVote, ForumPost, ForumPostVote
from app.database.models.messaging import DirectMessage, Notification
from app.database.models.mix import Mix, MixSegment
from app.database.models.mix_social import MixLike, SavedMix
from app.database.models.profile import Profile
from app.database.models.session import DJSession, SessionFeedback, UserPreference
from app.database.models.user import User

__all__ = [
    "User",
    "DJSession",
    "SessionFeedback",
    "UserPreference",
    "Mix",
    "MixSegment",
    "MixLike",
    "SavedMix",
    "Profile",
    "ForumPost",
    "ForumComment",
    "ForumPostVote",
    "ForumCommentVote",
    "DirectMessage",
    "Notification",
    "Attachment",
]
