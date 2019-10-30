"""
Compare mypy types.
"""

from __future__ import annotations

from enum import Enum
from os import linesep
from typing import Any, Dict, NamedTuple, Optional

from mypy.meet import is_overlapping_types
from mypy.nodes import (
    CONTRAVARIANT,
    COVARIANT,
    Decorator,
    SymbolNode,
    TypeAlias,
    TypeInfo,
    TypeVarExpr,
)
from mypy.subtypes import is_subtype
from mypy.types import CallableType, FunctionLike, Overloaded
from mypy.types import Type as TypeNode

from .types import RelevantSymbolNode
from .utils import (
    arg_star2_count,
    arg_star_count,
    get_expression_fullname,
    strict_kind_count,
)


class MatchResult(Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    NOT_FOUND = "not_found"
    MISLOCATED_SYMBOL = "mislocated_symbol"

    @classmethod
    def declare_mismatch(cls, matchResultString: str) -> MatchResult:
        err = matchResultString == MatchResult.MATCH.value

        try:
            result = MatchResult(matchResultString)
        except ValueError:
            err = True

        if err:
            possible_values = ", ".join(
                [f'"{m.value}"' for m in MatchResult if m is not MatchResult.MATCH]
            )
            raise ValueError(
                f'"{matchResultString}" is not a valid mismatch type.'
                f" (Use one of {possible_values}"
            )
        return result


def _get_symbol_type_info(symbol: SymbolNode) -> str:
    """
    Get the type of the given symbol as a human readable string.

    :param symbol: symbol for which to get the type
    """
    if isinstance(symbol, TypeAlias):
        return repr(symbol.target)
    if isinstance(symbol, TypeVarExpr):
        return _format_type_var(symbol)
    if isinstance(symbol, TypeInfo):
        return f"Class({symbol.fullname()})"

    return repr(getattr(symbol, "type", None))


class ComparisonResult(NamedTuple):
    """
    Result of comparing two symbol nodes and their types.
    """

    match_result: MatchResult
    """Type of comparison result"""

    symbol: RelevantSymbolNode
    """Symbol that was checked"""

    reference: Optional[SymbolNode]
    """Reference symbol that was checked against"""

    symbol_name: str
    """Full name of the symbol that was checked"""

    symbol_type: str
    """Type of the symbol that was checked"""

    reference_name: Optional[str]
    """Full name of the reference symbol"""

    reference_type: Optional[str]
    """Type of the reference symbol"""

    data: Optional[Dict[str, Any]] = None
    """Optional additional data"""

    message_val: Optional[str] = None
    """Optional message"""

    @property
    def message(self) -> str:
        """Human readable result of the comparison"""
        if self.message_val:
            return self.message_val

        if self.match_result is MatchResult.MATCH:
            return "\n".join(
                [
                    f"Types for {self.symbol_name} match:",
                    f"    {self.symbol_type}",
                    f"    {self.reference_type}",
                ]
            )
        elif self.match_result is MatchResult.MISMATCH:
            return "\n".join(
                [
                    f"Types for {self.symbol_name} do not match:",
                    f"    {self.symbol_type}",
                    f"    {self.reference_type}",
                ]
            )
        elif self.match_result is MatchResult.NOT_FOUND:
            return f'Symbol "{self.symbol_name}" not found in generated stubs'
        elif self.match_result is MatchResult.MISLOCATED_SYMBOL:
            return (
                f'Found symbol "{self.symbol_name}" in different location'
                f' "{self.reference_name}".'
            )

    @classmethod
    def create(
        cls,
        match_result: MatchResult,
        symbol: RelevantSymbolNode,
        reference: Optional[SymbolNode],
        data: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
    ) -> ComparisonResult:
        """
        Create a comparison result.

        :param match_result: if the match was successful
        :param symbol: symbol that was checked
        :param reference: reference symbol that was checked against
        :param data: optional additional data
        :param message: optional message
        """
        return cls(
            match_result=match_result,
            symbol=symbol,
            reference=reference,
            data=data,
            message_val=message,
            symbol_name=symbol.fullname(),
            symbol_type=_get_symbol_type_info(symbol),
            reference_name=reference.fullname() if reference else None,
            reference_type=_get_symbol_type_info(reference) if reference else None,
        )

    @classmethod
    def create_not_found(
        cls, symbol: RelevantSymbolNode, data: Optional[Dict[str, Any]] = None
    ) -> ComparisonResult:
        """
        Create an unsuccessful comparison result
        where there was no reference symbol found.

        :param symbol: symbol we wanted to check
        :param data: optional additional data
        :param message: optional message
        """
        return cls.create(
            match_result=MatchResult.NOT_FOUND, symbol=symbol, reference=None, data=data
        )

    @classmethod
    def create_mislocated_symbol(
        cls,
        symbol: RelevantSymbolNode,
        reference: SymbolNode,
        data: Optional[Dict[str, Any]] = None,
    ) -> ComparisonResult:
        """
        Create an unsuccessful comparison result where the reference symbol was found
        in a different level of the class hierarchy.

        :param symbol: symbol we wanted to check
        :param reference: symbol that was found somewhere else in the hierarchy
        :param data: optional additional data
        :param message: optional message
        """
        return cls.create(
            match_result=MatchResult.MISLOCATED_SYMBOL,
            symbol=symbol,
            reference=reference,
            data=data,
        )

    @classmethod
    def create_mismatch(
        cls,
        symbol: RelevantSymbolNode,
        reference: RelevantSymbolNode,
        data: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
    ) -> ComparisonResult:
        """
        Create an unsuccessful comparison result.

        :param symbol: symbol that was checked
        :param reference: reference symbol that was checked against
        :param data: optional additional data
        :param message: optional message
        """
        return cls.create(
            match_result=MatchResult.MISMATCH,
            symbol=symbol,
            reference=reference,
            data=data,
            message=message,
        )

    @classmethod
    def create_match(
        cls,
        symbol: RelevantSymbolNode,
        reference: RelevantSymbolNode,
        data: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
    ) -> ComparisonResult:
        """
        Create a successful comparison result.

        :param symbol: symbol that was checked
        :param reference: reference symbol that was checked against
        :param data: optional additional data
        :param message: optional message
        """
        return cls.create(
            match_result=MatchResult.MATCH,
            symbol=symbol,
            reference=reference,
            data=data,
            message=message,
        )


def _mypy_types_match(symbol_type: TypeNode, reference_type: TypeNode) -> MatchResult:
    """
    Check if the given symbol type matches the the reference type.

    :param symbol_type: symbol type to check
    :param reference_type: reference type to check against
    """
    if is_overlapping_types(symbol_type, reference_type) or is_subtype(
        symbol_type, reference_type
    ):
        return MatchResult.MATCH
    return MatchResult.MISMATCH


def _callable_types_match(
    callable_type: CallableType, reference_callable: CallableType
) -> MatchResult:
    """
    Check if the given callable matches the reference.

    :param callable_type: callable to check
    :param reference_callable: callable to check against
    """
    callable_kinds = callable_type.arg_kinds
    reference_kinds = reference_callable.arg_kinds

    strict_kind_count_callable = strict_kind_count(callable_kinds)
    strict_kind_count_reference = strict_kind_count(reference_kinds)

    if strict_kind_count_callable > strict_kind_count_reference:
        return MatchResult.MISMATCH

    arg_kinds_match = (
        strict_kind_count_callable == strict_kind_count_reference
        and arg_star_count(callable_kinds) <= arg_star_count(reference_kinds)
        and arg_star2_count(callable_kinds) <= arg_star2_count(reference_kinds)
    )

    if not arg_kinds_match:
        return MatchResult.MISMATCH

    return _mypy_types_match(callable_type, reference_callable)


def _overloaded_types_match(
    overloaded: Overloaded, reference_overloaded: Overloaded
) -> MatchResult:
    """
    Check if the given overloaded type matches the reference.

    :param overloaded: overloaded type to check
    :param reference_overloaded: overloaded type to check against
    """
    if len(overloaded.items()) != len(reference_overloaded.items()):
        return MatchResult.MISMATCH

    for ovl, ref in zip(overloaded.items(), reference_overloaded.items()):
        if _callable_types_match(ovl, ref) != MatchResult.MATCH:
            return MatchResult.MISMATCH

    return MatchResult.MATCH


def compare_mypy_types(
    symbol: RelevantSymbolNode,
    reference: RelevantSymbolNode,
    symbol_type: Optional[TypeNode],
    reference_type: Optional[TypeNode],
) -> ComparisonResult:
    """
    Check if the mypy type of given symbol node is compatible with the reference
    symbol.

    Returns a successful comparison if:

    -  the reference type is None (this means mypy doesn't have enough information)
    -  the symbol type is a subtype of the reference type
    -  the symbol type overlaps with the reference type

    :param symbol: symbol node to validate
    :param reference: symbol node to validate against
    :param symbol_type: type of the symbol to validate
    :param reference_type: type of the symbol to validate against
    """
    if reference_type is None:
        # MyPy does not have enough type information
        # hence we accept that our stub is correct
        return ComparisonResult.create_match(
            symbol=symbol, reference=reference, message="Generated type is None"
        )

    if symbol_type is None:
        return ComparisonResult.create_mismatch(symbol=symbol, reference=reference)

    match = MatchResult.MATCH

    if isinstance(symbol_type, CallableType) and isinstance(
        reference_type, CallableType
    ):
        match = _callable_types_match(symbol_type, reference_type)
    elif isinstance(symbol_type, Overloaded) and isinstance(reference_type, Overloaded):
        match = _overloaded_types_match(symbol_type, reference_type)
    else:
        match = _mypy_types_match(symbol_type, reference_type)

    return ComparisonResult.create(
        match_result=match, symbol=symbol, reference=reference
    )


def _type_infos_are_same_class(
    symbol: TypeInfo, reference: TypeInfo
) -> ComparisonResult:
    """
    Check if two TypeInfo symbols are the same class.

    This currently only does a comparison of the full name,
    since we only care if the classes are defined at the same location.
    The instance fields and methods are usually checked individually already.

    :param symbol: type info symbol to validate
    :param reference: type info symbol to validate against
    """
    if symbol.fullname() == reference.fullname():
        return ComparisonResult.create_match(symbol=symbol, reference=reference)
    else:
        return ComparisonResult.create_mismatch(symbol=symbol, reference=reference)


def _compare_type_aliases(symbol: TypeAlias, reference: TypeAlias) -> ComparisonResult:
    """
    Check if a TypeAlias symbol is a valid subtype of the given reference.

    This is done by comparing the target types of the aliases.

    :param symbol: type alias symbol to validate
    :param reference: type alias symbol to validate against
    """
    return compare_mypy_types(symbol, reference, symbol.target, reference.target)


def _format_type_var(symbol: TypeVarExpr) -> str:
    """
    Format a TypeVarExpr as it would be written in code.

    :param symbol: TypeVarExpr to format
    """

    variance = ""
    if symbol.variance == COVARIANT:
        variance = ", covariant=True"
    elif symbol.variance == CONTRAVARIANT:
        variance = ", contravariant=True"

    values = ""
    if symbol.values:
        values = ", " + (", ".join(str(t) for t in symbol.values))

    return f"{symbol.name} = TypeVar('{symbol.name()}'{values}{variance})"


def _compare_type_var_expr(
    symbol: TypeVarExpr, reference: TypeVarExpr
) -> ComparisonResult:
    """
    Check if a TypeVarExpr symbol matches the reference.

    Currently only implemented for type variables that have a bound but no values.

    :param symbol: type var symbol to validate
    :param reference: type var symbol to validate against
    :raises NotImplementedError: always
    """
    if not symbol.values and not reference.values:
        return compare_mypy_types(
            symbol, reference, symbol.upper_bound, reference.upper_bound
        )

    raise NotImplementedError(
        "Comparison of type variables (TypeVarExpr) with listed values is not"
        " implemented, encountered:"
        f"{linesep} - {_format_type_var(symbol)}"
        f"{linesep} - {_format_type_var(reference)}"
    )


def _compare_decorator(symbol: Decorator, reference: Decorator) -> ComparisonResult:
    """
    Check if Decorator symbol matches the reference

    Returns a successful comparision if:
        - all decorators are the same and applied in the same order,
        - the function these decorators are applied to match

    :param symbol: decorator symbol to validate
    :param reference: decorator symbol to validate against
    """

    symbol_decorators = list(map(get_expression_fullname, symbol.original_decorators))
    reference_decorators = list(
        map(get_expression_fullname, reference.original_decorators)
    )

    if symbol_decorators == reference_decorators:
        function_comparision = compare_symbols(symbol.func, reference.func)
        return ComparisonResult.create(
            match_result=function_comparision.match_result,
            symbol=symbol,
            reference=reference,
            data=function_comparision.data,
            message=function_comparision.message,
        )
    else:
        return ComparisonResult.create_mismatch(
            symbol=symbol,
            reference=reference,
            data={
                "Symbol decorators": symbol_decorators,
                "Reference decorators": reference_decorators,
            },
            message=(
                f"Function {symbol.func.fullname()} stubs have different decorators."
            ),
        )


def compare_symbols(
    symbol: RelevantSymbolNode, reference: RelevantSymbolNode
) -> ComparisonResult:
    """
    Check if the given symbol node is compatible with the reference symbol.

    Will return a successful comparison if any of the following holds:

    -  the symbols describe the same class

    -  the symbols are type aliases that resolve to the same type

    -  ``symbol`` is a valid subtype of ``reference``
       (see :py:func:`mypy.subtypes.is_subtype`)

    -  ``symbol`` and ``reference`` somehow overlap
       (see :py:func:`mypy.meet.is_overlapping_types`)

    :param symbol: symbol node to validate
    :param reference: symbol node to validate against
    """
    # TODO: Check if this is always the case, i.e. could there be
    # cases where `symbol` and `reference` don't have the same class but still match?
    if type(symbol) != type(reference):
        return ComparisonResult.create_mismatch(symbol=symbol, reference=reference)

    if isinstance(symbol, TypeInfo) and isinstance(reference, TypeInfo):
        return _type_infos_are_same_class(symbol, reference)

    if isinstance(symbol, TypeAlias) and isinstance(reference, TypeAlias):
        return _compare_type_aliases(symbol, reference)

    if isinstance(symbol, TypeVarExpr) and isinstance(reference, TypeVarExpr):
        return _compare_type_var_expr(symbol, reference)

    if isinstance(symbol, Decorator) and isinstance(reference, Decorator):
        return _compare_decorator(symbol, reference)

    symbol_type = getattr(symbol, "type")
    reference_type = getattr(reference, "type")

    if reference_type is None and isinstance(symbol_type, FunctionLike):
        return ComparisonResult.create_mismatch(symbol=symbol, reference=reference)

    return compare_mypy_types(
        symbol, reference, getattr(symbol, "type"), getattr(reference, "type")
    )
