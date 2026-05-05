var i = 0;
var settings = 0;
var text1 = ''; 
const audio = new Audio(AUDIO1_PATH);

function morseCodeConverter(input){
    const morseCode = {
        'A': '.-',     'B': '-...', 'C': '-.-.',
        'D': '-..',    'E': '.',    'F': '..-.',
        'G': '--.',    'H': '....', 'I': '..',
        'J': '.---',   'K': '-.-',  'L': '.-..',
        'M': '--',     'N': '-.',   'O': '---',
        'P': '.--.',   'Q': '--.-', 'R': '.-.',
        'S': '...',    'T': '-',    'U': '..-',
        'V': '...-',   'W': '.--',  'X': '-..-',
        'Y': '-.--',   'Z': '--..',
        '0': '-----',  '1': '.----', '2': '..---',
        '3': '...--',  '4': '....-', '5': '.....',
        '6': '-....',  '7': '--...', '8': '---..',
        '9': '----.',  '.': '.-.-.-', ',': '--..--',
        '-': '-....-', ':': '---...', '?': '..--..',
        "'": '.----.', '/': '-..-.'
    };
    return input.toUpperCase().split('').map(char => {
        return morseCode[char] || '';
    }).join(' ');
}
function onclick1(){
    text1 = document.getElementById('input').value;
    document.getElementById('output').value = morseCodeConverter(text1);
}
function onclick2(input){
    i = 0;
    var button = document.getElementById('button2');
    button.disabled = true;
    textTemp = morseCodeConverter(input);
    play(textTemp,0);
}
function off(){
    img.src = LIGHT_OFF;
    if (settings == 1){
        document.body.style.backgroundColor = '#454545';
    }
}
function on(){
    audio.play();
    img.src = LIGHT_ON;
    if (settings == 1){
        document.body.style.backgroundColor = 'white';
    }
}
// function lightOnShort(){
//     var img = document.getElementById('img');
//     img.src = 'on.png';
//     img.src = 'off.png';
// }
// function lightOnLong(){
//     var img = document.getElementById('img');
//     img.src = 'on.png';
//     img.src = 'off.png';
// }
function play(input,n){
    j = n;
    var button = document.getElementById('button2');
    off();
    if(j < input.length){
        if(input[j] == '.'){
            on();
            setTimeout(function(){
                play2(input,j+1);
            },70);
        }
        else if(input[j] == '-'){
            on();
            setTimeout(function(){
                play2(input,j+1);
            },200);
        }
        else {
            console.log("c");
            setTimeout(function(){
                play2(input,j+1);
            },100);
        }
    }
    if(j == input.length){
        button.disabled = false;
    }
}
function play2(input,n){
    audio.pause();
    off();
    audio.currentTime = 0;
    setTimeout(function(){
                play(input,n);
            },200);
}
function isSetted(event){
    if (event.target.checked){
        settings = 1;
        document.body.style.backgroundColor = '#454545';
    }
    else {
        settings = 0;
        document.body.style.backgroundColor = 'white';
    }
}

// script.js
document.addEventListener('DOMContentLoaded', function() {
    const volumeSlider = document.getElementById('volume-slider');

    // 设置初始音量
    volumeSlider.volume = audio.volume;

    // 监听滑块的变化
    volumeSlider.addEventListener('input', function() {
        audio.volume = this.value;
    });
});