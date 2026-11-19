from audit.receipts import receipt
from delivery.envelope import make_envelope
from delivery.runner import forward_pending_scope_request
from ledger.records import record
from replica.receive import accept_envelope
from replica.scope_request import change_scope
from replica.store import ReplicaStore
from tests.support import REPLICA, SUBSCRIPTION, WEST, WorkdayCase, totals, values


MARKER = 'SCOPE_CUTOVER_MISMATCH'


class CutoverIncidentTests(WorkdayCase):
    def _pending_with_old_tail(self):
        self.install_through_seven()
        change_scope(self.receiver, SUBSCRIPTION, 'R', WEST)
        self.assertEqual(record(self.source, 'correct', 'W', 'west', 19), 8)
        self.assertEqual(record(self.source, 'correct', 'E', 'east', 11), 9)
        old8, old9 = self.issue()
        self.assertEqual((old8.position, old9.position), (8, 9))
        return old9

    def test_cutover_receipt_matches_complete_book_and_new_tail(self):
        old9 = self._pending_with_old_tail()
        handoff = forward_pending_scope_request(self.source, self.receiver, SUBSCRIPTION)
        self.assertIsNotNone(handoff, MARKER)
        status = self.send(handoff).status
        proof = receipt(self.receiver, SUBSCRIPTION, 'R')
        report = self.report()
        fresh = self.issue()
        observed = (status, proof.position, report.position, report.scope, values(report.rows),
                    totals(report), tuple(piece.position for piece in fresh))
        self.assertEqual(observed, ('applied', 7, 7, WEST, (('W', 'west', 17, 3),),
                                    (('west', 1, 0, 17),), (8, 9)),
                         f'{MARKER} receipt, cutover book and new tail')
        new8, new9 = fresh
        self.assertEqual(self.send(new8).status, 'applied', MARKER)
        self.assertEqual(self.send(old9).status, 'retired', MARKER)
        self.assertEqual(self.send(new9).status, 'applied', MARKER)
        report = self.report()
        self.assertEqual((report.position, report.scope, values(report.rows)),
                         (9, WEST, (('W', 'west', 19, 8),)), MARKER)

    def test_legal_west_handoff_cannot_be_changed_by_late_east(self):
        old9 = self._pending_with_old_tail()
        west17 = {'observation_id': 'W', 'section': 'west', 'reading': '17', 'source_position': 3}
        west19 = {'observation_id': 'W', 'section': 'west', 'reading': '19', 'source_position': 8}
        handoff = make_envelope(SUBSCRIPTION, REPLICA, 2, 7, 'cutover', {
            'request_id': 'R', 'prior_version': 1, 'scope': ['west'], 'rows': [west17],
        })
        new8 = make_envelope(SUBSCRIPTION, REPLICA, 2, 8, 'delta', {
            'operation': 'upsert', 'row': west19,
        })
        self.assertEqual(accept_envelope(self.receiver, REPLICA, handoff).status, 'applied')
        self.assertEqual(accept_envelope(self.receiver, REPLICA, new8).status, 'applied')
        before = self.report()
        self.assertEqual((before.position, before.scope, values(before.rows)),
                         (8, WEST, (('W', 'west', 19, 8),)), MARKER)
        self.reopen()
        status = self.send(old9).status
        view = ReplicaStore(self.receiver).load_view(REPLICA)
        self.assertEqual((status, view.head.position, view.head.scope, values(view.rows)),
                         ('retired', 8, WEST, (('W', 'west', 19, 8),)),
                         f'{MARKER} old delivery changed the committed west replica')
        self.assertEqual(self.report(), before, MARKER)
        self.assertEqual(receipt(self.receiver, SUBSCRIPTION, 'R').position, 7, MARKER)
