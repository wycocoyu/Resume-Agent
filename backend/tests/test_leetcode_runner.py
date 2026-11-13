from __future__ import annotations

import shutil

import pytest
from pathlib import Path

from backend.services.leetcode_runner import LeetCodeRunner

pytestmark = pytest.mark.skipif(
    shutil.which("go") is None, reason="Go toolchain not installed"
)


def make_problem() -> dict:
    return {
        "slug": "reverse-nodes-in-k-group-full-tail",
        "functionName": "reverseKGroup",
        "signature": "func reverseKGroup(head *ListNode, k int) *ListNode",
        "judge": {"entry": "reverseKGroup"},
        "visibleTestCases": [
            {"id": "case-1", "input": {"head": [1, 2, 3, 4, 5, 6, 7, 8], "k": 3}, "expected": [3, 2, 1, 6, 5, 4, 8, 7]}
        ],
        "hiddenTestCases": [
            {"id": "hidden-1", "input": {"head": [1, 2], "k": 3}, "expected": [2, 1]}
        ],
    }


GOOD_CODE = """package main

type ListNode struct {
\tVal  int
\tNext *ListNode
}

func reverseKGroup(head *ListNode, k int) *ListNode {
\tdummy := &ListNode{Next: head}
\tpre := dummy
\tcur := head
\tfor cur != nil {
\t\ttail := cur
\t\tcount := 1
\t\tfor count < k && tail.Next != nil {
\t\t\ttail = tail.Next
\t\t\tcount++
\t\t}
\t\tnextGroup := tail.Next
\t\tnewHead, newTail := reverse(cur, tail)
\t\tpre.Next = newHead
\t\tnewTail.Next = nextGroup
\t\tpre = newTail
\t\tcur = nextGroup
\t}
\treturn dummy.Next
}

func reverse(head, tail *ListNode) (*ListNode, *ListNode) {
\tprev := tail.Next
\tcur := head
\tfor prev != tail {
\t\tnext := cur.Next
\t\tcur.Next = prev
\t\tprev = cur
\t\tcur = next
\t}
\treturn tail, head
}
"""


BAD_CODE = """package main

type ListNode struct {
\tVal  int
\tNext *ListNode
}

func reverseKGroup(head *ListNode, k int) *ListNode {
\treturn head
}
"""


STANDALONE_PROGRAM_CODE = """package main

import "fmt"

type ListNode struct {
\tVal  int
\tNext *ListNode
}

func reverseKGroup(head *ListNode, k int) *ListNode {
\tdummy := &ListNode{Next: head}
\tpre := dummy
\tcur := head
\tfor cur != nil {
\t\ttail := cur
\t\tcount := 1
\t\tfor count < k && tail.Next != nil {
\t\t\ttail = tail.Next
\t\t\tcount++
\t\t}
\t\tnextGroup := tail.Next
\t\tnewHead, newTail := reverse(cur, tail)
\t\tpre.Next = newHead
\t\tnewTail.Next = nextGroup
\t\tpre = newTail
\t\tcur = nextGroup
\t}
\treturn dummy.Next
}

func reverse(head, tail *ListNode) (*ListNode, *ListNode) {
\tprev := tail.Next
\tcur := head
\tfor prev != tail {
\t\tnext := cur.Next
\t\tcur.Next = prev
\t\tprev = cur
\t\tcur = next
\t}
\treturn tail, head
}

func buildList(nums []int) *ListNode {
\tdummy := &ListNode{}
\tcur := dummy
\tfor _, num := range nums {
\t\tcur.Next = &ListNode{Val: num}
\t\tcur = cur.Next
\t}
\treturn dummy.Next
}

func printList(head *ListNode) {
\tfor head != nil {
\t\tfmt.Print(head.Val)
\t\tif head.Next != nil {
\t\t\tfmt.Print(" -> ")
\t\t}
\t\thead = head.Next
\t}
\tfmt.Println()
}

func main() {
\thead := buildList([]int{1, 2, 3, 4, 5, 6, 7, 8})
\tk := 3
\tnewHead := reverseKGroup(head, k)
\tprintList(newHead)
}
"""


def test_run_cases_returns_pass_result(tmp_path: Path):
    runner = LeetCodeRunner(runtime_dir=tmp_path)
    result = runner.run_cases(make_problem(), GOOD_CODE, make_problem()["visibleTestCases"])

    assert result["status"] == "accepted"
    assert result["summary"]["passed"] == 1
    assert result["results"][0]["passed"] is True


def test_submit_problem_uses_hidden_cases(tmp_path: Path):
    runner = LeetCodeRunner(runtime_dir=tmp_path)
    result = runner.submit_problem(make_problem(), GOOD_CODE)

    assert result["status"] == "accepted"
    assert result["summary"]["total"] == 2


def test_submit_problem_returns_wrong_answer(tmp_path: Path):
    runner = LeetCodeRunner(runtime_dir=tmp_path)
    result = runner.submit_problem(make_problem(), BAD_CODE)

    assert result["status"] == "wrong_answer"
    assert any(not item["passed"] for item in result["results"])


def test_run_cases_accepts_standalone_program_by_ignoring_user_main(tmp_path: Path):
    runner = LeetCodeRunner(runtime_dir=tmp_path)
    result = runner.run_cases(make_problem(), STANDALONE_PROGRAM_CODE, make_problem()["visibleTestCases"])

    assert result["status"] == "accepted"
    assert result["results"][0]["passed"] is True


def make_class_problem() -> dict:
    return {
        "slug": "lru-cache",
        "functionName": "LRUCache",
        "signature": "",
        "judge": {
            "type": "class",
            "constructor": "Constructor",
            "className": "LRUCache",
            "methods": {
                "get": "Get",
                "put": "Put"
            },
            "voidMethods": ["put"],
        },
        "visibleTestCases": [
            {
                "id": "case-1",
                "input": {
                    "operations": ["LRUCache", "put", "put", "get", "put", "get", "put", "get", "get", "get"],
                    "arguments": [[2], [1, 1], [2, 2], [1], [3, 3], [2], [4, 4], [1], [3], [4]],
                },
                "expected": [None, None, None, 1, None, -1, None, -1, 3, 4],
            }
        ],
        "hiddenTestCases": [],
    }


GOOD_CLASS_CODE = """package main

type node struct {
\tkey  int
\tval  int
\tprev *node
\tnext *node
}

type LRUCache struct {
\tcap   int
\tcache map[int]*node
\thead  *node
\ttail  *node
}

func Constructor(capacity int) LRUCache {
\thead := &node{}
\ttail := &node{}
\thead.next = tail
\ttail.prev = head
\treturn LRUCache{
\t\tcap:   capacity,
\t\tcache: make(map[int]*node),
\t\thead:  head,
\t\ttail:  tail,
\t}
}

func (c *LRUCache) Get(key int) int {
\tif nd, ok := c.cache[key]; ok {
\t\tc.moveToFront(nd)
\t\treturn nd.val
\t}
\treturn -1
}

func (c *LRUCache) Put(key int, value int) {
\tif nd, ok := c.cache[key]; ok {
\t\tnd.val = value
\t\tc.moveToFront(nd)
\t\treturn
\t}
\tnd := &node{key: key, val: value}
\tc.cache[key] = nd
\tc.addFront(nd)
\tif len(c.cache) > c.cap {
\t\tremoved := c.tail.prev
\t\tc.remove(removed)
\t\tdelete(c.cache, removed.key)
\t}
}

func (c *LRUCache) addFront(nd *node) {
\tnd.prev = c.head
\tnd.next = c.head.next
\tc.head.next.prev = nd
\tc.head.next = nd
}

func (c *LRUCache) remove(nd *node) {
\tnd.prev.next = nd.next
\tnd.next.prev = nd.prev
}

func (c *LRUCache) moveToFront(nd *node) {
\tc.remove(nd)
\tc.addFront(nd)
}
"""


def test_run_cases_supports_class_style_problem(tmp_path: Path):
    runner = LeetCodeRunner(runtime_dir=tmp_path)
    result = runner.run_cases(make_class_problem(), GOOD_CLASS_CODE, make_class_problem()["visibleTestCases"])

    assert result["status"] == "accepted"
    assert result["summary"]["passed"] == 1
    assert result["results"][0]["actual"] == [None, None, None, 1, None, -1, None, -1, 3, 4]
