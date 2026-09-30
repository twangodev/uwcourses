import type { Stats } from "node:fs";
import { relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import type { WatchOptions } from "vite";

type DirectoryWatchOptions = {
  root: URL;
  include: string[];
  exclude: string[];
  includeRootFiles: boolean;
};

function containsPath(directory: string, path: string) {
  return path === directory || path.startsWith(`${directory}/`);
}

function isRootFile(path: string, stats?: Stats) {
  return !path.includes("/") && !stats?.isDirectory();
}

export function watchDirectories({
  root,
  include,
  exclude,
  includeRootFiles,
}: DirectoryWatchOptions): WatchOptions {
  const rootPath = fileURLToPath(root);

  return {
    ignored: (file: string, stats?: Stats) => {
      const path = relative(rootPath, file).split(sep).join("/");
      if (exclude.some((directory) => containsPath(directory, path)))
        return true;
      if (path === "" || (includeRootFiles && isRootFile(path, stats)))
        return false;

      const isIncludedPath = include.some((directory) =>
        containsPath(directory, path),
      );
      const leadsToIncludedDirectory = include.some((directory) =>
        containsPath(path, directory),
      );
      return !isIncludedPath && !leadsToIncludedDirectory;
    },
  };
}
