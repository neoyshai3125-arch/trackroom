/* Optional storefront and genre controls shared by the two search forms. */
window.TrackroomCatalogFilters = (() => {
  const countries = [
    ['', '기본 스토어'],
    ['KR', '대한민국'], ['US', '미국'], ['JP', '일본'],
    ['GB', '영국'], ['FR', '프랑스'], ['DE', '독일'],
  ];
  const genres = [
    ['', '전체 장르'],
    ['k-pop', 'K-팝'], ['j-pop', 'J-팝'], ['pop', '팝'],
    ['hip-hop', '힙합 / 랩'], ['rnb', 'R&B / 소울'], ['rock', '록'],
    ['indie', '인디 / 얼터너티브'], ['electronic', '일렉트로닉 / 댄스'],
    ['ballad', '발라드'], ['jazz', '재즈'], ['classical', '클래식'],
    ['soundtrack', 'OST / 사운드트랙'], ['latin', '라틴'],
  ];

  function appendField(parent, labelText, field, options, descriptionId) {
    const label = document.createElement('label');
    const title = document.createElement('span');
    title.textContent = labelText;
    const select = document.createElement('select');
    select.dataset.catalogFilter = field;
    select.setAttribute('aria-describedby', descriptionId);
    for (const [value, text] of options) select.add(new Option(text, value));
    label.append(title, select);
    parent.append(label);
    return select;
  }

  function mount(container, {platform = () => 'apple', onChange = () => {}} = {}) {
    const fields = document.createElement('div');
    fields.className = 'catalog-filter-fields';
    const description = document.createElement('p');
    description.id = container.id + 'Description';
    description.className = 'catalog-filter-description';
    const country = appendField(fields, '국가 · 스토어', 'country', countries, description.id);
    const genre = appendField(fields, '장르', 'genre', genres, description.id);
    container.replaceChildren(fields, description);
    fields.addEventListener('change', onChange);

    function update() {
      const supported = platform() === 'apple';
      fields.hidden = !supported;
      country.disabled = genre.disabled = !supported;
      description.textContent = supported
        ? '국가는 스토어 지역, 장르는 Apple 분류 기준이에요.'
        : '국가 · 스토어와 장르 필터는 Apple 검색에서 쓸 수 있어요.';
    }

    function params() {
      if (platform() !== 'apple') return {};
      const values = {};
      if (country.value) values.country = country.value;
      if (genre.value) values.genre = genre.value;
      return values;
    }

    function reset() {
      country.value = genre.value = '';
      update();
    }

    update();
    return {update, params, reset};
  }

  return {mount};
})();
