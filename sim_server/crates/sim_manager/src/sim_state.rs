// src/sim_state.rs
//
// Rust side simulation state definitions.

use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct SimState {
    pub sim_time: f64,
    pub parts: Vec<PartState>,
}

impl SimState {
    pub fn empty() -> Self {
        Self {
            sim_time: 0.0,
            parts: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct PartState {
    pub name: String,
    pub pos: [f64; 3],
    pub rot: [f64; 4],
}

impl PartState {
    pub fn new(name: impl Into<String>, pos: [f64; 3], rot: [f64; 4]) -> Self {
        Self {
            name: name.into(),
            pos,
            rot,
        }
    }
}
