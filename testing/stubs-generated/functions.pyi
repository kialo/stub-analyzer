from typing import Any, overload


def matching_function(foo: int, bar: str) -> str: ...
def additional_args(foo: int) -> str: ...
def additional_optional_args(foo:int) -> Any: ...

@overload
def overloaded_additional_args(foo: str) -> Any: ...
@overload
def overloaded_additional_args(foo: int, bar: int) -> Any: ...

@overload
def overloaded_additional_optional_args(foo: str) -> Any: ...
@overload
def overloaded_additional_optional_args(foo: int, bar: int) -> Any: ...

