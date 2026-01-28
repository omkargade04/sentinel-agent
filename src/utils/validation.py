"""
Validation Utilities for PR Review Pipeline

Provides utilities for validating and reconstructing objects at activity boundaries,
with proper error handling and type safety.
"""

from typing import List, Dict, Any, Union, TypeVar, Type
from enum import Enum

from src.models.schemas.pr_review.pr_patch import PRFilePatch, ChangeType
from src.models.schemas.pr_review.seed_set import SeedSetS0
from src.exceptions.pr_review_exceptions import (
    PatchReconstructionException,
    SeedSetReconstructionException,
    TypeCoercionException,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar('T', bound=Enum)


def safe_enum_value(value: Union[T, str], enum_class: Type[T]) -> str:
    """Safely extract string value from an enum or string.

    Handles the case where a value may be either:
    - An enum instance (returns .value)
    - A string (returns as-is)

    Args:
        value: Either an enum instance or string
        enum_class: The enum class for type checking

    Returns:
        The string value

    Raises:
        TypeCoercionException: If value is neither enum nor string
    """
    if isinstance(value, enum_class):
        return value.value
    elif isinstance(value, str):
        return value
    raise TypeCoercionException(
        field_name="enum_value",
        expected_type=f"{enum_class.__name__} or str",
        actual_type=type(value).__name__,
        value=str(value) if value is not None else None
    )


def validate_patches(
    patches_data: List[Dict[str, Any]],
    strict: bool = False
) -> List[PRFilePatch]:
    """Validate and reconstruct PRFilePatch objects from serialized data.

    This function handles the deserialization scenario where patches may have
    been serialized with use_enum_values=True, causing change_type to be a string.

    Args:
        patches_data: List of dicts to reconstruct as PRFilePatch objects
        strict: If True, raises on first error; if False, skips invalid patches

    Returns:
        List of validated PRFilePatch objects

    Raises:
        PatchReconstructionException: If strict=True and any patch fails validation
    """
    validated_patches = []
    errors = []

    for index, patch_dict in enumerate(patches_data):
        try:
            # If already a PRFilePatch, validate it's usable
            if isinstance(patch_dict, PRFilePatch):
                validated_patches.append(patch_dict)
                continue

            # Reconstruct from dict - Pydantic validator will normalize change_type
            patch = PRFilePatch(**patch_dict)
            validated_patches.append(patch)

        except Exception as e:
            error_detail = str(e)
            logger.warning(
                f"Failed to reconstruct patch at index {index}: {error_detail}",
                extra={
                    "patch_index": index,
                    "file_path": patch_dict.get("file_path", "unknown") if isinstance(patch_dict, dict) else "unknown",
                    "error_type": type(e).__name__,
                }
            )
            errors.append((index, error_detail))

            if strict:
                raise PatchReconstructionException(
                    patch_index=index,
                    error_detail=error_detail
                )

    if errors and not strict:
        logger.warning(
            f"Skipped {len(errors)} invalid patches during reconstruction",
            extra={"error_count": len(errors), "total_patches": len(patches_data)}
        )

    return validated_patches


def validate_seed_set(
    seed_set_data: Union[Dict[str, Any], SeedSetS0]
) -> SeedSetS0:
    """Validate and reconstruct a SeedSetS0 object from serialized data.

    Args:
        seed_set_data: Either a dict to reconstruct or an existing SeedSetS0

    Returns:
        Validated SeedSetS0 object

    Raises:
        SeedSetReconstructionException: If reconstruction fails
    """
    if isinstance(seed_set_data, SeedSetS0):
        return seed_set_data

    try:
        return SeedSetS0(**seed_set_data)
    except Exception as e:
        error_detail = str(e)
        logger.error(
            f"Failed to reconstruct seed set: {error_detail}",
            extra={"error_type": type(e).__name__}
        )
        raise SeedSetReconstructionException(error_detail=error_detail)


def validate_change_type(
    change_type: Union[ChangeType, str]
) -> ChangeType:
    """Validate and normalize a change_type value to ChangeType enum.

    Args:
        change_type: Either a ChangeType enum or string value

    Returns:
        ChangeType enum instance

    Raises:
        TypeCoercionException: If change_type is invalid
    """
    if isinstance(change_type, ChangeType):
        return change_type
    if isinstance(change_type, str):
        try:
            return ChangeType(change_type)
        except ValueError:
            raise TypeCoercionException(
                field_name="change_type",
                expected_type="ChangeType",
                actual_type="invalid str",
                value=change_type
            )
    raise TypeCoercionException(
        field_name="change_type",
        expected_type="ChangeType or str",
        actual_type=type(change_type).__name__,
        value=str(change_type)[:50] if change_type is not None else None
    )
