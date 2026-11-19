from audit.receipts import receipt
from delivery.runner import forward_pending_scope_request
from ledger.records import record
from replica.scope_request import change_scope
from tests.support import EAST, REPLICA, SUBSCRIPTION, WEST, WorkdayCase, totals, values


class CutoverRegressionTests(WorkdayCase):
    def test_empty_handoff_activates_and_retires_late_old_delta(self):
        self.assertEqual(record(self.source, 'register', 'E', 'east', 5), 1)
        self.install()
        self.assertEqual(record(self.source, 'correct', 'E', 'east', 9), 2)
        (old2,) = self.issue()
        change_scope(self.receiver, SUBSCRIPTION, 'R', WEST)
        cutover = forward_pending_scope_request(self.source, self.receiver, SUBSCRIPTION)
        self.assertEqual((cutover.position, cutover.payload['rows']), (1, []))
        self.assertEqual(self.send(cutover).status, 'applied')
        report = self.report()
        self.assertEqual((report.position, report.scope, report.rows), (1, WEST, ()))
        self.assertEqual(totals(report), (('west', 0, 0, 0),))
        self.assertEqual(receipt(self.receiver, SUBSCRIPTION, 'R').position, 1)
        self.assertEqual(self.send(old2).status, 'retired')
        self.assertEqual(self.report(), report)
        (new2,) = self.issue()
        self.assertEqual(new2.payload, {'operation': 'progress'})
        self.assertEqual(self.send(new2).status, 'applied')
        self.assertEqual((self.report().position, self.report().rows), (2, ()))

    def test_old_generation_delta_cannot_fill_gap_after_cutover(self):
        self.install_through_seven()
        change_scope(self.receiver, SUBSCRIPTION, 'R', WEST)
        self.assertEqual(record(self.source, 'correct', 'W', 'west', 19), 8)
        self.assertEqual(record(self.source, 'correct', 'W', 'west', 21), 9)
        old8, old9 = self.issue()
        cutover = forward_pending_scope_request(self.source, self.receiver, SUBSCRIPTION)
        new8, new9 = self.issue()
        self.assertEqual(self.send(new9).status, 'waiting')
        self.assertEqual(self.send(cutover).status, 'applied')
        self.assertEqual(self.send(old8).status, 'retired')
        self.assertEqual(self.send(old9).status, 'retired')
        report = self.report()
        self.assertEqual((report.position, report.scope, values(report.rows)),
                         (7, WEST, (('W', 'west', 17, 3),)))
        self.assertEqual(self.send(new8).status, 'applied')
        self.assertEqual(self.send(new9).status, 'applied')
        self.assertEqual((self.report().position, values(self.report().rows)),
                         (9, (('W', 'west', 21, 9),)))

    def test_cutover_to_wider_scope_backfills_never_delivered_rows(self):
        self.install_through_seven()
        change_scope(self.receiver, SUBSCRIPTION, 'R', ('west', 'east'))
        cutover = forward_pending_scope_request(self.source, self.receiver, SUBSCRIPTION)
        self.assertEqual(self.send(cutover).status, 'applied')
        report = self.report()
        self.assertEqual((report.position, report.scope, values(report.rows)),
                         (7, ('east', 'west'), (('E', 'east', 5, 7), ('W', 'west', 17, 3))))
        self.assertEqual(totals(report), (('east', 1, 0, 5), ('west', 1, 0, 17)))
        self.assertEqual(record(self.source, 'correct', 'W', 'west', 19), 8)
        (piece8,) = self.issue()
        self.assertEqual(self.send(piece8).status, 'applied')
        self.assertEqual(values(self.report().rows),
                         (('E', 'east', 5, 7), ('W', 'west', 19, 8)))
