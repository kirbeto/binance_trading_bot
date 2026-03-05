class LossGuard:
    def __init__(self, max_consecutive_losses: int):
        self.max_consecutive_losses = max_consecutive_losses
        self.loss_streak = 0

    def record(self, win: bool) -> None:
        if win:
            self.loss_streak = 0
        else:
            self.loss_streak += 1

    def can_trade(self) -> bool:
        return self.loss_streak < self.max_consecutive_losses
