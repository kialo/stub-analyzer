"""
API for analyzing Python stubs using mypy.
"""
from os.path import abspath
from typing import Generator, Iterable, Optional, Set, Union

from mypy.build import BuildResult, State, build
from mypy.fscache import FileSystemCache
from mypy.main import process_options
from mypy.nodes import (
    GDEF,
    MDEF,
    Decorator,
    FuncDef,
    MypyFile,
    OverloadedFuncDef,
    SymbolNode,
    TypeAlias,
    TypeInfo,
    TypeVarExpr,
    Var,
)

RelevantSymbolNode = Union[
    Decorator, FuncDef, OverloadedFuncDef, Var, TypeInfo, TypeVarExpr, TypeAlias
]
""" 
SymbolNodes that are interesting for stub files. 
Excludes MypyFiles (the modules themselves), imported names and Mypy placeholders 
"""


def _mypy_analyze(
    mypy_conf_path: str, root_path: str, stubs_path: Optional[str] = None
) -> BuildResult:
    """
    Parses and analyzes the types of the code in root_path.
    :param mypy_conf_path: path to a mypy.ini
    :param root_path: path to the code directory where the type analysis is started
    :param stubs_path: path to the directory of stubs for mypy to use
    :return: Mypy's analysis result
    """
    # The call to `build.build` is inspired by `mypy/mypy/main.py::main`
    # `build` is not a documented public API
    args = ["--config-file", mypy_conf_path, root_path]
    fscache = FileSystemCache()
    sources, options = process_options(args, fscache=fscache)
    if stubs_path is not None:
        options = options.apply_changes({"mypy_path": [stubs_path]})
    return build(sources, options, None, None, fscache)


def is_stubbed_module(module: State) -> bool:
    return module.path is not None and module.path.endswith(".pyi")


def collect_types(
    symbol_node: SymbolNode, collected_types: Optional[Set[str]] = None
) -> Generator[RelevantSymbolNode, None, None]:
    """
    Collects all relevant type definitions of the symbols in the given node.
    :param symbol_node: any symbol node, e.g. MypyFile (BuildResult.graph.tree)
    :param collected_types: used to avoid collecting duplicates
    """
    if not collected_types:
        collected_types = set()

    # ignore builtins because we don't provide stubs for them
    if "builtins" in symbol_node.fullname():
        return

    # do not collect types twice
    if symbol_node.fullname() in collected_types:
        return
    collected_types.add(symbol_node.fullname())

    if isinstance(symbol_node, MypyFile):
        # the symbol node represents a Python module
        for symbol in symbol_node.names.values():
            # only global and class member definitions are interesting
            if symbol.kind not in [GDEF, MDEF]:
                pass

            if symbol.node and symbol.module_public:
                yield from collect_types(symbol.node, collected_types)
    elif isinstance(symbol_node, TypeInfo):
        # the symbol represents a class definition
        yield symbol_node
        for class_member in symbol_node.names.values():
            if class_member.node:
                yield from collect_types(class_member.node, collected_types)
    elif isinstance(
        symbol_node,
        (Decorator, FuncDef, OverloadedFuncDef, Var, TypeAlias, TypeVarExpr),
    ):
        # the symbol represents a function definition, variable, type alias or generic TypeVar
        yield symbol_node
    else:
        assert False, f"Unexpected symbol type {type(symbol_node)}"


def get_stub_types(
    stubs_path: str, mypy_conf_path: str, root_path: Optional[str] = None
) -> Generator[RelevantSymbolNode, None, None]:
    """
    Analyzes the stub files in stubs_path and returns module and class definitions of stubs as symbol nodes.
    Only relevant symbol nodes (e.g. for variables, functions, classes, methods) are returned. They contain the
    type annotation information.
    :param stubs_path: where all the stub files are located
    :param mypy_conf_path: path to mypy.ini
    :param root_path: path to the code directory where the type analysis is started
    """
    stubs_path = abspath(stubs_path)

    if root_path:
        build_result = _mypy_analyze(mypy_conf_path, root_path, stubs_path)
    else:
        build_result = _mypy_analyze(mypy_conf_path, stubs_path)

    stubbed_modules = {
        module
        for module in build_result.graph.values()
        if module.path
        and is_stubbed_module(module)
        and module.path.startswith(stubs_path)
    }

    for module in stubbed_modules:
        if module.tree:
            yield from collect_types(module.tree)


def _print_graph_data(stub_types: Iterable[RelevantSymbolNode]) -> None:
    for symbol in stub_types:
        if hasattr(symbol, "type"):
            print(f"{symbol.fullname()}: {symbol.type}")
        else:
            type_name = (
                "Class" if isinstance(symbol, TypeInfo) else type(symbol).__name__
            )
            print(f"{symbol.fullname()} ({type_name})")
