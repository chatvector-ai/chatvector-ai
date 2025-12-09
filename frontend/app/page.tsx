export default function Home() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 dark:from-gray-900 dark:to-blue-900">
      <div className="container mx-auto px-4 py-16">
        {/* Giant Header */}
        <div className="text-center mb-16">
          <h1 className="text-7xl md:text-9xl font-black bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent mb-6">
            ChatVector AI
          </h1>
          <p className="text-2xl md:text-3xl text-gray-600 dark:text-gray-300 mb-8 max-w-3xl mx-auto">
            Have conversations with your documents
          </p>
          <div className="text-lg text-gray-500 dark:text-gray-400 max-w-2xl mx-auto">
            Upload PDFs, ask questions, get answers. Powered by AI.
          </div>
        </div>

        {/* Status & Call to Action */}
        <div className="max-w-4xl mx-auto">
          <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl p-8 mb-8">
            <h2 className="text-3xl font-bold text-gray-900 dark:text-white mb-6 text-center">
              🚀 Ready for Contributors!
            </h2>

            <div className="text-center">
              <p className="text-lg text-gray-700 dark:text-gray-300 mb-6">
                This is a community-driven open source project. Help us build
                the future of document intelligence!
              </p>

              <div className="flex flex-col sm:flex-row gap-4 justify-center">
                <a
                  href="https://github.com/chatvector-ai/chatvector-ai"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center px-6 py-3 bg-gray-900 dark:bg-white text-white dark:text-gray-900 rounded-lg font-semibold hover:bg-gray-700 dark:hover:bg-gray-200 transition-colors"
                >
                  📁 View on GitHub
                </a>
                <a
                  href="https://github.com/chatvector-ai/chatvector-ai/issues"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center px-6 py-3 border-2 border-gray-900 dark:border-white text-gray-900 dark:text-white rounded-lg font-semibold hover:bg-gray-900 hover:text-white dark:hover:bg-white dark:hover:text-gray-900 transition-colors"
                >
                  🛠️ Start Contributing
                </a>
              </div>
            </div>
          </div>

          {/* Quick Links */}
          <div className="text-center">
            <div className="text-sm text-gray-400">
              Built with Next.js, FastAPI, and ❤️ by the open source community
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
