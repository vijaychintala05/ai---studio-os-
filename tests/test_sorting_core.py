"""The offline sorter behind the 7 pm evening status: splitting, the seven categories, Hinglish, unsorted when unsure, and an accuracy
measurement on a small FICTIONAL corpus. The measured figure is a regression guard for this rule set only; it is not the accuracy
the owner will hold a live model to (no target has been supplied)."""
import pytest

from studioos import sorting_core as s

CORPUS = [
    # critical_issue
    ('There is a crack in the south wall of Villa A', 'critical_issue'),
    ('Urgent: water leaking from the terrace slab', 'critical_issue'),
    ('A worker was injured, accident on site', 'critical_issue'),
    ('Lift installation is blocked because of a wrong drawing', 'critical_issue'),
    ('Plumbing pipe broken near the kitchen', 'critical_issue'),
    ('Seepage problem in the basement', 'critical_issue'),
    ('Kitchen mein dikkat hai', 'critical_issue'),
    ('Pipe toot gaya second floor par', 'critical_issue'),
    ('Critical delay on structural approval', 'critical_issue'),
    ('Unsafe scaffolding on the east side', 'critical_issue'),
    # task_done
    ('Slab pour completed at Villa B', 'task_done'),
    ('Submitted the drawings to the client', 'task_done'),
    ('Tiles delivered to site', 'task_done'),
    ('Electrical conduit work finished', 'task_done'),
    ('Painting done on the ground floor', 'task_done'),
    ('Samples sent to the client', 'task_done'),
    ('Plastering ho gaya', 'task_done'),
    ('Drawing bhej diya client ko', 'task_done'),
    ('Footing excavation complete', 'task_done'),
    ('Handed over keys for Flat 4', 'task_done'),
    # pending_task
    ('Window frames still pending', 'pending_task'),
    ('Waiting for the vendor to confirm the rate card', 'pending_task'),
    ('Flooring not yet started on the second floor', 'pending_task'),
    ('Approval from the municipality is delayed', 'pending_task'),
    ('Painting baaki hai', 'pending_task'),
    ('Electrical fittings abhi nahi aaye', 'pending_task'),
    ('Two rooms remaining for waterproofing', 'pending_task'),
    ('Site clearance is incomplete', 'pending_task'),
    ('Marble order is waiting for payment', 'pending_task'),
    ('Welding work left on the gate', 'pending_task'),
    # progress
    ('Visited the Mehta Villa site and measured the walls', 'progress'),
    ('Brickwork is going on, 12 workers on site', 'progress'),
    ('Tiling in progress at the bathroom', 'progress'),
    ('Inspection of the shuttering done at the first floor', 'progress'),
    ('Site visit with the structural engineer', 'progress'),
    ('Labour attendance was good, work chal raha hai', 'progress'),
    ('Plastering started on the north wall', 'progress'),
    ('Roof slab work in progress, about 60 percent', 'progress'),
    ('Villa C site progress is on track', 'progress'),
    ('Painting work started in the hall', 'progress'),
    # decision
    ('Client approved the kitchen layout', 'decision'),
    ('We decided to use vitrified tiles', 'decision'),
    ('Agreed with the vendor to take the older rate', 'decision'),
    ('Layout finalised and signed off by the owner', 'decision'),
    ('Elevation option B confirmed', 'decision'),
    ('Client said no to the glass railing', 'decision'),
    ('Design tay hua, option two', 'decision'),
    ('Owner rejected the false ceiling quote', 'decision'),
    ('Approval given for extra labour', 'decision'),
    ('Final decision: teak doors only', 'decision'),
    # financial
    ('Paid Rs 25,000 to the tile vendor', 'financial'),
    ('Bought 40 bags of cement for Rs 14,800', 'financial'),
    ('Received advance of 2 lakh from the client', 'financial'),
    ('Invoice for the electrician is 18,500 rupees', 'financial'),
    ('Cash payment of 3,200 for labour', 'financial'),
    ('Purchase order for steel raised, 4 lakh', 'financial'),
    ('Ramesh ko 5000 rs bhugtan kiya', 'financial'),
    ('Cheque of Rs 50,000 deposited', 'financial'),
    ('Quotation received for the lift, 9 lakh', 'financial'),
    ('GST bill of Rs 1,200 for fittings', 'financial'),
    # tomorrow
    ('Tomorrow we pour the second floor slab', 'tomorrow'),
    ('Will visit Villa A tomorrow morning', 'tomorrow'),
    ('Kal ko tiles ka kaam shuru karenge', 'tomorrow'),
    ('Plan to meet the client tmrw at 11', 'tomorrow'),
    ('Tomorrow the carpenter starts on the wardrobes', 'tomorrow'),
    ('Scheduled the plumber for tomorrow', 'tomorrow'),
    ('Agle din painting karna hai', 'tomorrow'),
    ('Tomorrow site inspection with the architect', 'tomorrow'),
    ('Going to order the sanitaryware tomorrow', 'tomorrow'),
    ('Tomorrow collect the revised drawings', 'tomorrow'),
]


def test_split_reply_pieces():
    pieces = s.split_reply('Slab pour done. Paid Rs 5,000 to the vendor!\n- Will visit tomorrow\n\nok')
    assert pieces == ['Slab pour done.', 'Paid Rs 5,000 to the vendor!', 'Will visit tomorrow']      # one per sentence; filler dropped
    assert s.split_reply('') == [] and s.split_reply(None) == [] and len(s.split_reply('a long one. ' * 100)) == 40


def test_the_seven_categories_are_the_evening_headings():
    from studioos import rhythm_core as c
    assert set(s.LABELS.values()) == set(c.EVENING_HEADINGS)


@pytest.mark.parametrize('text,want', [
    ('Paid Rs 25,000 to the tile vendor', 'financial'),
    ('Slab pour completed at Villa B', 'task_done'),
    ('Tomorrow we pour the slab', 'tomorrow'),
    ('Crack in the south wall', 'critical_issue'),
])
def test_clear_sentences(text, want):
    got = s.classify(text)
    assert got['category'] == want and got['confidence'] > 0.4


def test_unsure_pieces_are_left_for_the_person():
    out = s.sort_reply('Had chai with Ramesh. The weather was nice')
    assert all(p['category'] == 'unsorted' and p['needs_review'] and p['label'] == 'Not sure' for p in out)
    mixed = s.classify('Tiling done but flooring still pending')                                       # both signals: low confidence
    assert mixed['category'] in ('task_done', 'pending_task') and mixed['confidence'] < 0.7


def test_a_whole_reply_is_sorted_piece_by_piece():
    reply = 'Slab pour completed at Villa B. Paid Rs 25,000 to the tile vendor. There is a crack in the south wall. Will visit tomorrow.'
    got = [(p['category']) for p in s.sort_reply(reply)]
    assert got == ['task_done', 'financial', 'critical_issue', 'tomorrow']


def test_measured_accuracy_on_the_fictional_corpus():
    r = s.accuracy(CORPUS)
    assert r['total'] == 70 and set(r['by_category']) == set(s.CATEGORIES)
    assert r['accuracy'] >= 0.85, r                              # regression guard for this rule set, not a target
    for cat, (right, total) in r['by_category'].items():
        assert total == 10 and right >= 7, (cat, r['by_category'])
