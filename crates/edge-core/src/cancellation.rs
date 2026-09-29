//! A linearizable dispatch fence, shared with admission/cancellation callers.
//! This is coordination, not authentication. Only trusted host code creates it.
use std::{
    sync::{Arc, Mutex},
    time::Instant,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CancelDisposition {
    PreventedDispatch,
    PossiblyDispatched,
    AlreadyFinished,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DispatchDecision {
    Proceed,
    Cancelled,
    Expired,
}
#[derive(Default)]
struct State {
    cancelled: bool,
    dispatched: bool,
    finished: bool,
}
#[derive(Clone, Default)]
pub struct DispatchControl(Arc<Mutex<State>>);
impl DispatchControl {
    pub fn cancel(&self) -> CancelDisposition {
        let mut state = self.0.lock().unwrap_or_else(|e| e.into_inner());
        if state.finished {
            return CancelDisposition::AlreadyFinished;
        }
        state.cancelled = true;
        if state.dispatched {
            CancelDisposition::PossiblyDispatched
        } else {
            CancelDisposition::PreventedDispatch
        }
    }
    pub fn cancelled(&self) -> bool {
        self.0.lock().map_or(true, |state| state.cancelled)
    }
    /// Call exactly once, after durable intent and immediately before invoking the adapter.
    /// Cancellation after this point cannot promise no dispatch, even if bytes have not left.
    pub fn begin_dispatch(&self, deadline: Instant) -> DispatchDecision {
        let Ok(mut state) = self.0.lock() else {
            return DispatchDecision::Cancelled;
        };
        if state.cancelled || state.finished || state.dispatched {
            return DispatchDecision::Cancelled;
        }
        if Instant::now() >= deadline {
            return DispatchDecision::Expired;
        }
        state.dispatched = true;
        DispatchDecision::Proceed
    }
    pub fn finish(&self) {
        self.0.lock().unwrap_or_else(|e| e.into_inner()).finished = true;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{thread, time::Duration};
    #[test]
    fn cancellation_and_dispatch_have_one_winner() {
        for _ in 0..100 {
            let control = DispatchControl::default();
            let other = control.clone();
            let cancel = thread::spawn(move || other.cancel());
            let dispatch = control.begin_dispatch(Instant::now() + Duration::from_secs(1));
            let cancellation = cancel.join().unwrap();
            assert!(matches!(
                (dispatch, cancellation),
                (
                    DispatchDecision::Proceed,
                    CancelDisposition::PossiblyDispatched
                ) | (
                    DispatchDecision::Cancelled,
                    CancelDisposition::PreventedDispatch
                )
            ));
        }
    }
    #[test]
    fn expiry_and_completion_never_allow_another_dispatch() {
        let control = DispatchControl::default();
        assert_eq!(
            control.begin_dispatch(Instant::now()),
            DispatchDecision::Expired
        );
        control.finish();
        assert_eq!(control.cancel(), CancelDisposition::AlreadyFinished);
        assert_eq!(
            control.begin_dispatch(Instant::now() + Duration::from_secs(1)),
            DispatchDecision::Cancelled
        );
    }
}
