const path = require("path");

module.exports = {
  webpack: {
    configure: (webpackConfig) => {
      webpackConfig.resolve.fallback = {
        ...webpackConfig.resolve.fallback,
        fs: false,
        path: false,
        zlib: false,
        worker_threads: false,
      };

      // Force fflate to use the browser ESM build instead of the Node CJS build.
      // The $ suffix means exact match only, so "fflate/browser" won't hit this alias.
      webpackConfig.resolve.alias = {
        ...webpackConfig.resolve.alias,
        "fflate$": path.resolve(__dirname, "node_modules/fflate/esm/browser.js"),
        "fflate/browser": path.resolve(
          __dirname,
          "node_modules/fflate/esm/browser.js"
        ),
      };

      return webpackConfig;
    },
  },
};
