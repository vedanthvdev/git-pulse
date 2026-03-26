class GitPulse < Formula
  include Language::Python::Virtualenv

  desc "Background Git repository updater — keeps your default branches fresh"
  homepage "https://github.com/vedanthvasudev/git-pulse"
  url "https://github.com/vedanthvasudev/git-pulse/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "PLACEHOLDER_SHA256"
  license "MIT"

  depends_on "python@3.12"

  resource "typer" do
    url "https://files.pythonhosted.org/packages/source/t/typer/typer-0.15.1.tar.gz"
    sha256 "PLACEHOLDER"
  end

  resource "click" do
    url "https://files.pythonhosted.org/packages/source/c/click/click-8.1.8.tar.gz"
    sha256 "PLACEHOLDER"
  end

  resource "rich" do
    url "https://files.pythonhosted.org/packages/source/r/rich/rich-13.9.4.tar.gz"
    sha256 "PLACEHOLDER"
  end

  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/source/P/PyYAML/pyyaml-6.0.2.tar.gz"
    sha256 "PLACEHOLDER"
  end

  resource "gitpython" do
    url "https://files.pythonhosted.org/packages/source/G/GitPython/gitpython-3.1.44.tar.gz"
    sha256 "PLACEHOLDER"
  end

  resource "gitdb" do
    url "https://files.pythonhosted.org/packages/source/g/gitdb/gitdb-4.0.12.tar.gz"
    sha256 "PLACEHOLDER"
  end

  resource "smmap" do
    url "https://files.pythonhosted.org/packages/source/s/smmap/smmap-5.0.2.tar.gz"
    sha256 "PLACEHOLDER"
  end

  resource "markdown-it-py" do
    url "https://files.pythonhosted.org/packages/source/m/markdown-it-py/markdown_it_py-3.0.0.tar.gz"
    sha256 "PLACEHOLDER"
  end

  resource "mdurl" do
    url "https://files.pythonhosted.org/packages/source/m/mdurl/mdurl-0.1.2.tar.gz"
    sha256 "PLACEHOLDER"
  end

  resource "pygments" do
    url "https://files.pythonhosted.org/packages/source/P/Pygments/pygments-2.19.1.tar.gz"
    sha256 "PLACEHOLDER"
  end

  resource "shellingham" do
    url "https://files.pythonhosted.org/packages/source/s/shellingham/shellingham-1.5.4.tar.gz"
    sha256 "PLACEHOLDER"
  end

  resource "typing-extensions" do
    url "https://files.pythonhosted.org/packages/source/t/typing_extensions/typing_extensions-4.12.2.tar.gz"
    sha256 "PLACEHOLDER"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/git-pulse --version")
  end
end
