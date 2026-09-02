# Maintainer: Chris Buchan Pham
pkgname=bulk-edit-calendar
pkgver=0.1.0
pkgrel=1
pkgdesc="Local, privacy-conscious bulk editor for Google Calendar"
arch=('any')
url="https://github.com/chrisbuchanpham/Bulk-Edit-Calendar-CachyOS"
license=('MIT')
depends=('python' 'python-fastapi' 'uvicorn' 'python-jinja' 'python-pydantic'
         'python-google-api-python-client' 'python-google-auth-oauthlib'
         'python-keyring' 'python-platformdirs')
makedepends=('python-build' 'python-installer' 'python-hatchling' 'python-wheel')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')

build() {
  cd "Bulk-Edit-Calendar-CachyOS-$pkgver"
  python -m build --wheel --no-isolation
}

package() {
  cd "Bulk-Edit-Calendar-CachyOS-$pkgver"
  python -m installer --destdir="$pkgdir" dist/*.whl
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}

