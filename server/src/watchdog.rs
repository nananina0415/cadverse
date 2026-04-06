use std::path::PathBuf;
use std::time::Duration;
use std::sync::{Arc, Mutex};
use anyhow::Result;
use notify::RecursiveMode;
use notify_debouncer_mini::new_debouncer;

// ── 핸들 ──────────────────────────────────────────────────────────────────────

pub struct Watchdog<T> {
    pub folder: PathBuf,
    pub data: Arc<Mutex<Option<T>>>,
    debouncer: notify_debouncer_mini::Debouncer<notify::RecommendedWatcher>,
}

impl<T: Send + 'static> Watchdog<T> {
    pub fn new<F>(folder: PathBuf, on_change: F) -> Result<Self>
    where
        F: Fn(PathBuf, &Arc<Mutex<Option<T>>>) + Send + 'static,
    {
        let data: Arc<Mutex<Option<T>>> = Arc::new(Mutex::new(None));
        let data_cb = data.clone();
        let folder_clone = folder.clone();
        let mut debouncer = new_debouncer(Duration::from_millis(500), move |events: notify_debouncer_mini::DebounceEventResult| {
            if events.is_ok() {
                on_change(folder_clone.clone(), &data_cb);
            }
        })?;

        debouncer.watcher().watch(&folder, RecursiveMode::NonRecursive)?;

        Ok(Self { folder, data, debouncer })
    }

    pub fn set_folder(&mut self, folder: PathBuf) -> Result<()> {
        let _ = self.debouncer.watcher().unwatch(&self.folder);
        self.debouncer.watcher().watch(&folder, RecursiveMode::NonRecursive)?;
        self.folder = folder;
        Ok(())
    }
}
