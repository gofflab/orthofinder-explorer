"""Minimal Newick parsing and species-tree helpers.

The web app only needs topology (who is sister to whom) to order species and to
assign phylostrata, so this module avoids importing ``ete3`` into the request
path.  Trees are represented as plain nested dictionaries::

    {"name": "Octopus_chierchiae", "length": 0.12, "children": []}

which also happens to be the shape ``d3.hierarchy`` expects on the client.
"""

from __future__ import annotations


class NewickError(ValueError):
    """Raised when a Newick string cannot be parsed."""


def _new_node():
    """Return an empty tree node.

    Returns:
        Dict with ``name`` (str), ``length`` (float or None) and ``children``
        (list of nodes).
    """
    return {"name": "", "length": None, "children": []}


def parse_newick(text):
    """Parse a Newick string into a nested dictionary tree.

    Supports quoted labels, branch lengths, internal node labels / support
    values, and ``[...]`` comments.  Only the first tree in the string is read.

    Args:
        text: Newick-formatted tree, with or without the trailing semicolon.

    Returns:
        The root node as a dict with ``name``, ``length`` and ``children``.

    Raises:
        NewickError: If the string is empty or its parentheses are unbalanced.
    """
    if not text or not text.strip():
        raise NewickError("Empty Newick string")

    root = _new_node()
    current = root
    stack = []          # ancestors of ``current``
    token = []          # characters of the label / length being read
    reading_length = False
    i = 0
    n = len(text)

    def flush():
        """Assign the buffered token to the current node as name or length."""
        nonlocal reading_length
        value = "".join(token).strip()
        token.clear()
        if reading_length:
            try:
                current["length"] = float(value)
            except ValueError:
                current["length"] = None
        elif value:
            current["name"] = value
        reading_length = False

    while i < n:
        ch = text[i]
        if ch == "[":
            # Skip bracketed comments (e.g. NHX annotations).
            end = text.find("]", i)
            i = n if end == -1 else end + 1
            continue
        if ch in "'\"":
            # Quoted label: copy verbatim up to the matching quote.
            end = text.find(ch, i + 1)
            if end == -1:
                raise NewickError("Unterminated quoted label")
            token.append(text[i + 1:end])
            i = end + 1
            continue
        if ch == "(":
            child = _new_node()
            current["children"].append(child)
            stack.append(current)
            current = child
        elif ch == ",":
            flush()
            if not stack:
                raise NewickError("Unexpected ',' outside of a clade")
            child = _new_node()
            stack[-1]["children"].append(child)
            current = child
        elif ch == ")":
            flush()
            if not stack:
                raise NewickError("Unbalanced ')' in Newick string")
            current = stack.pop()
        elif ch == ":":
            flush()
            reading_length = True
        elif ch == ";":
            break
        else:
            token.append(ch)
        i += 1

    flush()
    if stack:
        raise NewickError("Unbalanced '(' in Newick string")
    return root


def leaf_names(node):
    """List leaf names under a node in left-to-right (display) order.

    Args:
        node: Tree node produced by :func:`parse_newick`.

    Returns:
        List of leaf name strings.
    """
    if not node["children"]:
        return [node["name"]]
    names = []
    for child in node["children"]:
        names.extend(leaf_names(child))
    return names


def prune_to_leaves(node, keep):
    """Return a copy of the tree restricted to the requested leaves.

    Internal nodes left with a single child are collapsed so that every
    remaining internal node represents a real split among the kept leaves.

    Args:
        node: Tree node produced by :func:`parse_newick`.
        keep: Collection of leaf names to retain.

    Returns:
        A new pruned node, or None when no requested leaf lies below ``node``.
    """
    keep = set(keep)
    if not node["children"]:
        if node["name"] in keep:
            return {"name": node["name"], "length": node["length"], "children": []}
        return None
    children = [c for c in (prune_to_leaves(ch, keep) for ch in node["children"]) if c]
    if not children:
        return None
    if len(children) == 1:
        # Collapse the unary node, summing branch lengths where both exist.
        child = children[0]
        if node["length"] is not None and child["length"] is not None:
            child["length"] = node["length"] + child["length"]
        return child
    return {"name": node["name"], "length": node["length"], "children": children}


def lineage_clades(node, leaf):
    """Describe the nested clades along the path from the root to a leaf.

    Args:
        node: Root of a (preferably pruned) species tree.
        leaf: Name of the focal leaf.

    Returns:
        List ordered from the root (oldest split) to the leaf itself.  Each
        entry is a list of the leaf names in the clade at that depth; the last
        entry is ``[leaf]``.  Returns an empty list when the leaf is absent.
    """
    names = leaf_names(node)
    if leaf not in names:
        return []
    path = [names]
    current = node
    while current["children"]:
        for child in current["children"]:
            child_names = leaf_names(child)
            if leaf in child_names:
                path.append(child_names)
                current = child
                break
    return path
