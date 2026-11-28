from ops.compare_recreated import missing_added_lines


def test_comparison_reports_dropped_additions_including_duplicate_lines():
    assert missing_added_lines(
        b'keep\nrepeat\nold\n',
        b'keep\nrepeat\nrepeat\nnew\n',
        b'keep\nrepeat\nold\n',
    ) == [b'repeat', b'new']


def test_comparison_accepts_reordered_additions_and_ignores_removed_old_lines():
    assert missing_added_lines(b'old\n', b'old\nfirst\nsecond\n', b'second\nfirst\n') == []
