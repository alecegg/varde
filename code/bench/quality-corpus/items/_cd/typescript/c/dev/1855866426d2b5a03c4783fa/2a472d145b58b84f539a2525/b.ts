// SPDX-License-Identifier: Apache-2.0

function removeFile(file: WatchedFile) {
                    watchedFiles = copyListRemovingItem(file, watchedFiles);
                }

function createWatchedFileSet() {
                const dirWatchers = createFileMap<DirectoryWatcher>();
                // One file can have multiple watchers
                const fileWatcherCallbacks = createFileMap<FileWatcherCallback[]>();
                return { addFile, removeFile };

                function reduceDirWatcherRefCountForFile(filePath: Path) {
                    const dirPath = getDirectoryPath(filePath);
                    if (dirWatchers.contains(dirPath)) {
                        const watcher = dirWatchers.get(dirPath);
                        watcher.referenceCount -= 1;
                        if (watcher.referenceCount <= 0) {
                            watcher.close();
                            dirWatchers.remove(dirPath);
                        }
                    }
                }

                function addDirWatcher(dirPath: Path): void {
                    if (dirWatchers.contains(dirPath)) {
                        const watcher = dirWatchers.get(dirPath);
                        watcher.referenceCount += 1;
                        return;
                    }

                    const watcher: DirectoryWatcher = _fs.watch(
                        dirPath,
                        { persistent: true },
                        (eventName: string, relativeFileName: string) => fileEventHandler(eventName, relativeFileName, dirPath)
                    );
                    watcher.referenceCount = 1;
                    dirWatchers.set(dirPath, watcher);
                    return;
                }

                function addFileWatcherCallback(filePath: Path, callback: FileWatcherCallback): void {
                    if (fileWatcherCallbacks.contains(filePath)) {
                        fileWatcherCallbacks.get(filePath).push(callback);
                    }
                    else {
                        fileWatcherCallbacks.set(filePath, [callback]);
                    }
                }

                function addFile(filePath: Path, callback: FileWatcherCallback): WatchedFile {
                    addFileWatcherCallback(filePath, callback);
                    addDirWatcher(getDirectoryPath(filePath));

                    return { filePath, callback };
                }

                function removeFile(watchedFile: WatchedFile) {
                    removeFileWatcherCallback(watchedFile.filePath, watchedFile.callback);
                    reduceDirWatcherRefCountForFile(watchedFile.filePath);
                }

                function removeFileWatcherCallback(filePath: Path, callback: FileWatcherCallback) {
                    if (fileWatcherCallbacks.contains(filePath)) {
                        const newCallbacks = copyListRemovingItem(callback, fileWatcherCallbacks.get(filePath));
                        if (newCallbacks.length === 0) {
                            fileWatcherCallbacks.remove(filePath);
                        }
                        else {
                            fileWatcherCallbacks.set(filePath, newCallbacks);
                        }
                    }
                }

                /**
                 * @param watcherPath is the path from which the watcher is triggered.
                 */
                function fileEventHandler(eventName: string, relativefileName: string, baseDirPath: Path) {
                    // When files are deleted from disk, the triggered "rename" event would have a relativefileName of "undefined"
                    const filePath = relativefileName === undefined ? undefined : toPath(relativefileName, baseDirPath, getCanonicalPath);
                    if (eventName === "change" && fileWatcherCallbacks.contains(filePath)) {
                        for (const fileCallback of fileWatcherCallbacks.get(filePath)) {
                            fileCallback(filePath);
                        }
                    }
                }
            }

function reduceDirWatcherRefCountForFile(filePath: Path) {
                    const dirPath = getDirectoryPath(filePath);
                    if (dirWatchers.contains(dirPath)) {
                        const watcher = dirWatchers.get(dirPath);
                        watcher.referenceCount -= 1;
                        if (watcher.referenceCount <= 0) {
                            watcher.close();
                            dirWatchers.remove(dirPath);
                        }
                    }
                }

function removeFile(watchedFile: WatchedFile) {
                    removeFileWatcherCallback(watchedFile.filePath, watchedFile.callback);
                    reduceDirWatcherRefCountForFile(watchedFile.filePath);
                }

function removeFileWatcherCallback(filePath: Path, callback: FileWatcherCallback) {
                    if (fileWatcherCallbacks.contains(filePath)) {
                        const newCallbacks = copyListRemovingItem(callback, fileWatcherCallbacks.get(filePath));
                        if (newCallbacks.length === 0) {
                            fileWatcherCallbacks.remove(filePath);
                        }
                        else {
                            fileWatcherCallbacks.set(filePath, newCallbacks);
                        }
                    }
                }